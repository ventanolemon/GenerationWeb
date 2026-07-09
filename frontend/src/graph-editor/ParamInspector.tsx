// Инспектор параметров: ОДНА общая форма, генерируемая из params_schema
// каталога ({type, default, optional, values}) — кастомных форм под типы
// узлов нет (по брифу скелета). Тип "subgraph" — кнопка «Открыть тело…»
// (вход во вложенный холст); "file"/"hidden" на вебе — заглушка (ресурсный
// API — вне контракта §4.3).

import { useEffect, useState } from "react";
import type { Catalog, ParamSchema } from "./types";
import { catalogNode } from "./model";
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
      case "hidden":
        return (
          <span className={styles.inspectorNote}>
            (серверный ресурс — вне скелета)
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
