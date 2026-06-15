import { useEffect, useState } from "react";
import type { PartitionEditData } from "../../api/types";
import { api } from "../../api/client";
import Modal from "../Modal";
import mstyles from "../../styles/modal.module.css";

interface Props {
  subjectId: number;
  partitionId: number | null;
  onSaved: (newId: number) => void;
  onClose: () => void;
}

interface VarState {
  min: string;
  max: string;
  kind: string;
  step: string;
  forbidden: string;
  dimension: string;
}

const VAR_KINDS = ["auto", "natural", "integer", "real"];
const RESULT_KINDS = ["real", "natural", "integer"];

// Извлекает имена переменных вида #name# из текста условия
function parseVarNames(text: string): string[] {
  const seen: string[] = [];
  const re = /#([A-Za-zА-Яа-яЁё_][\w]*)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (!seen.includes(m[1])) seen.push(m[1]);
  }
  return seen;
}

/**
 * Конструктор физической задачи (constracted=1).
 * Структура generation_params описана в десктопном FisicEditor.
 */
export default function FisicEditorModal({ subjectId, partitionId, onSaved, onClose }: Props) {
  const [name, setName] = useState("");
  const [condition, setCondition] = useState("");
  const [resultLetter, setResultLetter] = useState("");
  const [formula, setFormula] = useState("");
  const [dimension, setDimension] = useState("");
  const [resultKind, setResultKind] = useState("real");
  const [resultMin, setResultMin] = useState("");
  const [resultMax, setResultMax] = useState("");
  const [varStates, setVarStates] = useState<Record<string, VarState>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Актуальный список переменных из условия
  const varNames = parseVarNames(condition);

  useEffect(() => {
    if (!partitionId) return;
    setLoading(true);
    api.getPartitionForEdit(partitionId)
      .then((data: PartitionEditData) => {
        setName(data.name);
        const cfg = data.generation_params as {
          condition?: string;
          result_letter?: string;
          formula?: string;
          dimension?: string;
          result?: { kind?: string; min?: unknown; max?: unknown };
          variables?: Record<string, {
            min?: unknown; max?: unknown; kind?: string;
            step?: unknown; forbidden?: unknown[]; dimension?: string;
          }>;
        };
        if (cfg.condition) setCondition(cfg.condition);
        if (cfg.result_letter) setResultLetter(cfg.result_letter);
        if (cfg.formula) setFormula(cfg.formula);
        if (cfg.dimension) setDimension(cfg.dimension);
        if (cfg.result?.kind) setResultKind(cfg.result.kind);
        if (cfg.result?.min != null) setResultMin(String(cfg.result.min));
        if (cfg.result?.max != null) setResultMax(String(cfg.result.max));
        if (cfg.variables) {
          const vs: Record<string, VarState> = {};
          for (const [k, v] of Object.entries(cfg.variables)) {
            vs[k] = {
              min: v.min != null ? String(v.min) : "",
              max: v.max != null ? String(v.max) : "",
              kind: v.kind ?? "auto",
              step: v.step != null ? String(v.step) : "",
              forbidden: Array.isArray(v.forbidden) ? v.forbidden.join(", ") : "",
              dimension: v.dimension ?? "",
            };
          }
          setVarStates(vs);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [partitionId]);

  function updateVar(vname: string, field: keyof VarState, value: string) {
    setVarStates((prev) => ({
      ...prev,
      [vname]: { ...(prev[vname] ?? { min: "", max: "", kind: "auto", step: "", forbidden: "", dimension: "" }), [field]: value },
    }));
  }

  function getVar(vname: string): VarState {
    return varStates[vname] ?? { min: "", max: "", kind: "auto", step: "", forbidden: "", dimension: "" };
  }

  async function handleSave() {
    if (!name.trim()) { setError("Введите название задачи."); return; }
    if (!condition.trim()) { setError("Введите текст условия."); return; }
    if (!formula.trim()) { setError("Введите формулу."); return; }
    if (!resultLetter.trim()) { setError("Укажите искомую величину."); return; }
    if (varNames.length === 0) { setError("В условии нет переменных (#имя#)."); return; }

    const variables: Record<string, unknown> = {};
    for (const vname of varNames) {
      const st = getVar(vname);
      if (!st.min || !st.max) {
        setError(`Переменная ${vname}: укажите минимум и максимум.`);
        return;
      }
      const entry: Record<string, unknown> = {
        min: st.min,
        max: st.max,
        kind: st.kind,
        dimension: st.dimension,
      };
      if (st.step) entry.step = st.step;
      if (st.forbidden.trim()) {
        entry.forbidden = st.forbidden.split(",").map((s) => s.trim()).filter(Boolean);
      }
      variables[vname] = entry;
    }

    const payload: Record<string, unknown> = {
      condition: condition.trim(),
      result_letter: resultLetter.trim(),
      formula: formula.trim(),
      dimension: dimension.trim(),
      variables,
    };
    if (resultKind !== "real" || resultMin || resultMax) {
      const rc: Record<string, unknown> = { kind: resultKind };
      if (resultMin) rc.min = resultMin;
      if (resultMax) rc.max = resultMax;
      payload.result = rc;
    }

    setSaving(true);
    setError(null);
    try {
      const result = await api.upsertPartition({
        subject_id: subjectId,
        name: name.trim(),
        constracted: 1,
        generation_params: payload,
      });
      onSaved(result.partition_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={partitionId ? "Редактирование физической задачи" : "Создание физической задачи"}
      onClose={onClose}
      width={700}
    >
      {loading ? (
        <div>Загрузка…</div>
      ) : (
        <>
          {error && <div className={mstyles.errorMsg}>{error}</div>}

          <div className={mstyles.formRow}>
            <label className={mstyles.formLabel}>Название задачи:</label>
            <input className={mstyles.formInput} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>

          <div className={mstyles.formRow}>
            <label className={mstyles.formLabel}>
              Условие (используйте #имя# для переменных):
            </label>
            <textarea
              className={mstyles.formTextarea}
              value={condition}
              onChange={(e) => setCondition(e.target.value)}
              rows={3}
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr 1fr", gap: "0.6rem", marginBottom: "0.9rem" }}>
            <div className={mstyles.formRow} style={{ marginBottom: 0 }}>
              <label className={mstyles.formLabel}>Искомая величина:</label>
              <input className={mstyles.formInput} value={resultLetter} onChange={(e) => setResultLetter(e.target.value)} placeholder="F" />
            </div>
            <div className={mstyles.formRow} style={{ marginBottom: 0 }}>
              <label className={mstyles.formLabel}>Формула:</label>
              <input className={mstyles.formInput} value={formula} onChange={(e) => setFormula(e.target.value)} placeholder="m * a" />
            </div>
            <div className={mstyles.formRow} style={{ marginBottom: 0 }}>
              <label className={mstyles.formLabel}>Размерность:</label>
              <input className={mstyles.formInput} value={dimension} onChange={(e) => setDimension(e.target.value)} placeholder="Н" />
            </div>
          </div>

          <details style={{ marginBottom: "0.9rem" }}>
            <summary style={{ cursor: "pointer", fontSize: "0.9rem", color: "#555" }}>
              Ограничения на результат (необязательно)
            </summary>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.6rem", marginTop: "0.6rem" }}>
              <div className={mstyles.formRow} style={{ marginBottom: 0 }}>
                <label className={mstyles.formLabel}>Тип:</label>
                <select className={mstyles.formSelect} value={resultKind} onChange={(e) => setResultKind(e.target.value)}>
                  {RESULT_KINDS.map((k) => <option key={k}>{k}</option>)}
                </select>
              </div>
              <div className={mstyles.formRow} style={{ marginBottom: 0 }}>
                <label className={mstyles.formLabel}>Min:</label>
                <input className={mstyles.formInput} value={resultMin} onChange={(e) => setResultMin(e.target.value)} placeholder="необязательно" />
              </div>
              <div className={mstyles.formRow} style={{ marginBottom: 0 }}>
                <label className={mstyles.formLabel}>Max:</label>
                <input className={mstyles.formInput} value={resultMax} onChange={(e) => setResultMax(e.target.value)} placeholder="необязательно" />
              </div>
            </div>
          </details>

          {varNames.length > 0 && (
            <div className={mstyles.formRow}>
              <label className={mstyles.formLabel}>Переменные:</label>
              <div style={{ border: "1px solid #ddd", borderRadius: 4, overflow: "hidden" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                  <thead style={{ background: "#f4f4f4" }}>
                    <tr>
                      {["Переменная", "Min", "Max", "Тип", "Шаг", "Запрещённые", "Размерность"].map((h) => (
                        <th key={h} style={{ padding: "0.3rem 0.5rem", borderBottom: "1px solid #ddd", textAlign: "left", fontWeight: 600 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {varNames.map((vname) => {
                      const st = getVar(vname);
                      const cell = (field: keyof VarState, placeholder?: string) => (
                        <td key={field} style={{ padding: "0.2rem 0.4rem" }}>
                          <input
                            style={{ width: "100%", padding: "0.2rem", border: "1px solid #bbb", borderRadius: 3, font: "inherit" }}
                            value={st[field]}
                            onChange={(e) => updateVar(vname, field, e.target.value)}
                            placeholder={placeholder}
                          />
                        </td>
                      );
                      return (
                        <tr key={vname} style={{ borderBottom: "1px solid #f0f0f0" }}>
                          <td style={{ padding: "0.3rem 0.5rem", fontWeight: 600 }}>{vname}</td>
                          {cell("min", "min")}
                          {cell("max", "max")}
                          <td style={{ padding: "0.2rem 0.4rem" }}>
                            <select
                              style={{ width: "100%", padding: "0.2rem", border: "1px solid #bbb", borderRadius: 3, font: "inherit" }}
                              value={st.kind}
                              onChange={(e) => updateVar(vname, "kind", e.target.value)}
                            >
                              {VAR_KINDS.map((k) => <option key={k}>{k}</option>)}
                            </select>
                          </td>
                          {cell("step", "шаг")}
                          {cell("forbidden", "1, 2, 3")}
                          {cell("dimension", "кг")}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className={mstyles.modalFooter}>
            <button className={mstyles.btnCancel} onClick={onClose}>Отмена</button>
            <button className={mstyles.btnSave} onClick={handleSave} disabled={saving}>
              {saving ? "Сохранение…" : "Сохранить"}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
