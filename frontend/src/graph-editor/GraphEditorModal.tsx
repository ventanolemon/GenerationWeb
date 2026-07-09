// Граф-редактор (constracted=4): палитра + холст + инспектор + вложенные
// холсты (хлебные крошки). Полноэкранный — холсту нужно место, обычный
// Modal мал.
//
// Интеграция API (контракт §2): каталог — один раз при открытии;
// /graph/validate — с дебаунсом после каждой правки; /graph/preview — по
// кнопке; сохранение — существующий upsert партиций (constracted=4,
// граф в generation_params КАК ЕСТЬ — состояние редактора и есть
// GraphSpec.to_dict()-совместимый JSON).

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { PartitionEditData } from "../api/types";
import { graphApi } from "./api";
import type { Catalog, PreviewResponse, ValidateResponse } from "./types";
import { toWire } from "./model";
import { EditorProvider, useEditor } from "./store";
import Canvas from "./Canvas";
import Palette from "./Palette";
import ParamInspector from "./ParamInspector";
import PreviewPanel from "./PreviewPanel";
import styles from "../styles/graph-editor.module.css";

interface Props {
  subjectId: number;
  partitionId: number | null; // null — создание нового раздела
  onSaved: (newId: number) => void;
  onClose: () => void;
}

export default function GraphEditorModal(props: Props) {
  return (
    <EditorProvider>
      <GraphEditorInner {...props} />
    </EditorProvider>
  );
}

const VALIDATE_DEBOUNCE_MS = 700;
const PREVIEW_SEEDS = [0, 1, 2];

function GraphEditorInner({ subjectId, partitionId, onSaved, onClose }: Props) {
  const { state, dispatch } = useEditor();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [name, setName] = useState("");
  const [fatal, setFatal] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [validation, setValidation] = useState<ValidateResponse | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  // ─── Загрузка: каталог (один раз) + партиция при редактировании ────────

  useEffect(() => {
    graphApi
      .catalog()
      .then(setCatalog)
      .catch((e) => setFatal(String(e)));
  }, []);

  useEffect(() => {
    if (partitionId == null) return;
    api
      .getPartitionForEdit(partitionId)
      .then((data: PartitionEditData) => {
        setName(data.name);
        dispatch({ kind: "load", spec: data.generation_params });
      })
      .catch((e) => setFatal(String(e)));
  }, [partitionId, dispatch]);

  // ─── Живая валидация с дебаунсом ────────────────────────────────────────

  const validateTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!catalog) return;
    if (validateTimer.current !== null) window.clearTimeout(validateTimer.current);
    validateTimer.current = window.setTimeout(() => {
      graphApi
        .validate(toWire(state.spec))
        .then(setValidation)
        .catch(() => setValidation(null)); // сервис недоступен — не мешаем правкам
    }, VALIDATE_DEBOUNCE_MS);
    return () => {
      if (validateTimer.current !== null) window.clearTimeout(validateTimer.current);
    };
  }, [state.spec, catalog]);

  // ─── Действия ────────────────────────────────────────────────────────────

  const runPreview = useCallback(() => {
    setPreviewOpen(true);
    setPreviewLoading(true);
    graphApi
      .preview(toWire(state.spec), PREVIEW_SEEDS)
      .then(setPreview)
      .catch((e) =>
        setPreview({ ok: false, errors: [String(e)], runs: [] }),
      )
      .finally(() => setPreviewLoading(false));
  }, [state.spec]);

  async function save() {
    if (!name.trim()) {
      setStatus("Укажите имя раздела.");
      return;
    }
    setSaving(true);
    try {
      const res = await api.upsertPartition({
        subject_id: subjectId,
        name: name.trim(),
        constracted: 4,
        generation_params: toWire(state.spec),
      });
      dispatch({ kind: "mark_saved" });
      onSaved(res.partition_id);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function requestClose() {
    if (state.dirty && !window.confirm("Есть несохранённые правки. Закрыть?")) {
      return;
    }
    onClose();
  }

  // ─── Рендер ──────────────────────────────────────────────────────────────

  if (fatal) {
    return (
      <div className={styles.overlay}>
        <div className={styles.fatal}>
          <p>{fatal}</p>
          <p className={styles.fatalHint}>
            Проверьте, что generator_service запущен и /api/graph проксируется
            (vite.config.ts).
          </p>
          <button onClick={onClose}>Закрыть</button>
        </div>
      </div>
    );
  }
  if (!catalog) {
    return (
      <div className={styles.overlay}>
        <div className={styles.fatal}>Загружаю каталог узлов…</div>
      </div>
    );
  }

  const vErr = validation && !validation.ok ? validation.errors[0] : null;

  return (
    <div className={styles.overlay}>
      <div className={styles.editorFrame}>
        <div className={styles.toolbar}>
          <input
            className={styles.nameInput}
            placeholder="Имя раздела"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />

          {/* Хлебные крошки вложенных холстов */}
          <div className={styles.breadcrumbs}>
            <button
              className={styles.crumb}
              disabled={state.path.length === 0}
              onClick={() => dispatch({ kind: "go_to_level", depth: 0 })}
            >
              Корень
            </button>
            {state.path.map((ref, i) => (
              <span key={`${ref.nodeId}.${ref.paramKey}`}>
                {" › "}
                <button
                  className={styles.crumb}
                  disabled={i === state.path.length - 1}
                  onClick={() => dispatch({ kind: "go_to_level", depth: i + 1 })}
                >
                  {ref.nodeId}.{ref.paramKey}
                </button>
              </span>
            ))}
            {state.path.length > 0 && (
              <button
                className={styles.crumbUp}
                onClick={() => dispatch({ kind: "exit_subgraph" })}
              >
                ↑ Наверх
              </button>
            )}
          </div>

          <div className={styles.toolbarSpacer} />
          <button className={styles.toolBtn} onClick={runPreview}>
            Предпросмотр
          </button>
          <button
            className={styles.toolBtnPrimary}
            disabled={saving}
            onClick={save}
          >
            {saving ? "Сохраняю…" : "Сохранить"}
          </button>
          <button className={styles.toolBtn} onClick={requestClose}>
            Закрыть
          </button>
        </div>

        <div className={styles.statusLine}>
          {status ||
            (vErr
              ? `✗ ${vErr}`
              : validation?.ok
                ? `✓ Граф корректен${validation.result_node ? ` · выход: ${validation.result_node}` : ""}`
                : "…")}
        </div>

        <div className={styles.workArea}>
          <Palette catalog={catalog} />
          <Canvas catalog={catalog} onStatus={setStatus} />
          <ParamInspector catalog={catalog} />
          {previewOpen && (
            <PreviewPanel
              preview={preview}
              loading={previewLoading}
              onClose={() => setPreviewOpen(false)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
