// Инспектор параметров: ОДНА общая форма, генерируемая из params_schema
// каталога ({type, default, optional, values}) — кастомных форм под типы
// узлов нет (по брифу скелета). Тип "subgraph" — кнопка «Открыть тело…»
// (вход во вложенный холст); "hidden" не показывается.
//
// Файловый параметр — выбор из ПОСТАВКИ по идентификатору `res:…`, а не
// ввод пути. Путь верен ровно на той машине, где его выбрали: граф с
// путём, собранный на десктопе, на сервере падает «файл не найден»
// (замер — core/graph/resources.py). Идентификатор разрешается
// относительно resources/ той машины, которая исполняет граф, поэтому
// работает всюду. Путь, пришедший из старого графа, показывается как
// есть и помечается непереносимым — молча стирать чужую работу нельзя.

import { useEffect, useState } from "react";
import type { Catalog, GraphResource, ParamSchema } from "./types";
import { catalogNode } from "./model";
import { graphApi } from "./api";
import { useEditor } from "./store";
import styles from "../styles/graph-editor.module.css";

interface Props {
  catalog: Catalog;
}

export default function ParamInspector({ catalog }: Props) {
  const { state, dispatch, current } = useEditor();
  const node = current.nodes.find((n) => n.id === state.selection) ?? null;

  // Черновики текстовых полей: коммит в модель по blur/Enter, чтобы каждое
  // нажатие клавиши не пересчитывало порты/провода (маркеры #x# в text
  // меняют входы узла — это дорогая правка).
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  useEffect(() => setDrafts({}), [state.selection]);

  // Список поставочных файлов: один запрос на открытие редактора. Пустой
  // список — не ошибка: установка может не поставлять ресурсов вовсе,
  // и тогда файловый параметр честно говорит, что выбирать нечего.
  const [resources, setResources] = useState<GraphResource[] | null>(null);
  useEffect(() => {
    let alive = true;
    graphApi.resources()
      .then((list) => { if (alive) setResources(list); })
      .catch(() => { if (alive) setResources([]); });
    return () => { alive = false; };
  }, []);

  if (!node) {
    return (
      <div className={styles.inspector}>
        <div className={styles.inspectorEmpty}>
          Выберите узел, чтобы редактировать параметры.
        </div>
      </div>
    );
  }

  const cn = catalogNode(catalog, node.type);
  const schema = cn?.params_schema ?? {};
  const params = node.params ?? {};

  function commit(key: string, value: unknown) {
    const next = { ...params };
    if (value === undefined) delete next[key];
    else next[key] = value;
    dispatch({ kind: "set_params", nodeId: node!.id, params: next, catalog });
  }

  function commitDraft(key: string, s: ParamSchema, raw: string) {
    setDrafts((d) => {
      const next = { ...d };
      delete next[key];
      return next;
    });
    switch (s.type) {
      case "int": {
        const v = parseInt(raw, 10);
        commit(key, Number.isFinite(v) ? v : undefined);
        break;
      }
      case "number": {
        const v = parseFloat(raw.replace(",", "."));
        commit(key, Number.isFinite(v) ? v : undefined);
        break;
      }
      case "list":
        // Список строк — по одной на строку textarea ('имя:тип' у imports и т.п.)
        commit(
          key,
          raw.split("\n").map((x) => x.trim()).filter(Boolean),
        );
        break;
      default:
        commit(key, raw);
    }
  }

  function draftValue(key: string, s: ParamSchema): string {
    if (key in drafts) return drafts[key];
    const v = params[key] ?? s.default;
    if (v == null) return "";
    if (s.type === "list" && Array.isArray(v)) return v.map(String).join("\n");
    return String(v);
  }

  /**
   * Файловый параметр: выпадающий список поставочных файлов.
   *
   * Список отбирается по `resource` из СХЕМЫ параметра, а не по типу
   * узла: какие файлы кому подходят, знает язык, и повторять это здесь
   * значило бы завести второй источник правды, расходящийся с первым.
   */
  function renderFile(key: string, s: ParamSchema) {
    const current = String(params[key] ?? s.default ?? "");
    const kind = s.resource;
    const list = (resources ?? []).filter((r) => !kind || r.kind === kind);
    const foreign = current !== "" && !current.startsWith("res:");
    return (
      <div className={styles.fileParam}>
        <select
          value={foreign ? "" : current}
          onChange={(e) => commit(key, e.target.value || undefined)}
        >
          <option value="">— не выбрано —</option>
          {list.map((r) => (
            <option key={r.id} value={r.id}>{r.title}</option>
          ))}
        </select>
        {resources !== null && list.length === 0 && (
          <span className={styles.inspectorNote}>
            в поставке нет файлов этого вида
          </span>
        )}
        {foreign && (
          // Путь не стираем: это чужая работа, и графы с локальными
          // файлами на десктопе работают. Но и молчать нельзя — на
          // сервере такой граф упадёт «файл не найден».
          <span className={styles.inspectorWarn} title={current}>
            путь с другой машины: <code>{current}</code> — на сервере не
            откроется, выберите файл из поставки
          </span>
        )}
      </div>
    );
  }

  function renderField(key: string, s: ParamSchema) {
    switch (s.type) {
      case "subgraph": {
        const body = params[key];
        const n =
          body && typeof body === "object" && Array.isArray((body as { nodes?: unknown[] }).nodes)
            ? (body as { nodes: unknown[] }).nodes.length
            : 0;
        return (
          <button
            className={styles.subgraphBtn}
            onClick={() =>
              dispatch({ kind: "enter_subgraph", nodeId: node!.id, paramKey: key })
            }
          >
            Открыть тело… ({n} узл.)
          </button>
        );
      }
      case "enum":
        return (
          <select
            value={String(params[key] ?? s.default ?? "")}
            onChange={(e) => commit(key, e.target.value)}
          >
            {(s.values ?? []).map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        );
      case "bool":
        return (
          <input
            type="checkbox"
            checked={Boolean(params[key] ?? s.default ?? false)}
            onChange={(e) => commit(key, e.target.checked)}
          />
        );
      case "file":
        return renderFile(key, s);
      case "hidden":
        return (
          <span className={styles.inspectorNote}>
            (служебный параметр — правится не здесь)
          </span>
        );
      case "text":
      case "list":
        return (
          <textarea
            rows={s.type === "text" ? 4 : 3}
            value={draftValue(key, s)}
            onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))}
            onBlur={(e) => commitDraft(key, s, e.target.value)}
          />
        );
      default: // string | int | number
        return (
          <input
            type="text"
            value={draftValue(key, s)}
            onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))}
            onBlur={(e) => commitDraft(key, s, e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
          />
        );
    }
  }

  return (
    <div className={styles.inspector}>
      <div className={styles.inspectorTitle}>
        {cn?.display_name || node.type}
        <span className={styles.inspectorId}>{node.id}</span>
      </div>
      {cn?.description && (
        <div className={styles.inspectorDesc}>{cn.description}</div>
      )}
      {Object.keys(schema).length === 0 && (
        <div className={styles.inspectorEmpty}>Нет параметров.</div>
      )}
      {Object.entries(schema).map(([key, s]) => (
        <label key={key} className={styles.inspectorField}>
          <span className={styles.inspectorLabel}>
            {key}
            {s.optional ? "" : " *"}
          </span>
          {renderField(key, s)}
        </label>
      ))}
      <button
        className={styles.deleteNodeBtn}
        onClick={() => dispatch({ kind: "remove_node", nodeId: node.id })}
      >
        Удалить узел
      </button>
    </div>
  );
}
