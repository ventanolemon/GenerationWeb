// Состояние редактора: один useReducer над иммутабельным корневым
// GraphSpecJson + путь текущего подграфа + выделение.
//
// ПОЧЕМУ useReducer, а не Zustand/Redux: состояние редактора — ОДНО
// иммутабельное значение (корневой JSON), все мутации — чистые функции
// model.ts, адресованные путём. Библиотека состояния не добавила бы здесь
// ничего, кроме зависимости: селекторы тривиальны (текущий подграф =
// getSubgraph(spec, path)), подписки на срезы не нужны (редактор — один
// экран), а time-travel/undo при желании ложится на историю значений spec.
// Требование брифа — «вложенные подграфы как данные» — выполняется самим
// форматом: см. комментарий в model.ts.

import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";
import type {
  Catalog,
  GraphEdgeJson,
  GraphPath,
  GraphSpecJson,
} from "./types";
import {
  addEdge,
  addNode,
  emptyGraph,
  getSubgraph,
  moveNode,
  normalizeGraph,
  removeEdge,
  removeNode,
  setParams,
  updateAtPath,
} from "./model";

export interface EditorState {
  spec: GraphSpecJson;      // корневой граф — единственный источник правды
  path: GraphPath;          // стек «где мы»: [] = корень, [{rep_1, body}] = тело
  selection: string | null; // id выделенного узла ТЕКУЩЕГО подграфа
  dirty: boolean;           // были ли правки с последней загрузки/сохранения
}

export type EditorAction =
  | { kind: "load"; spec: unknown }
  | { kind: "add_node"; typeId: string; params: Record<string, unknown>; x: number; y: number }
  | { kind: "remove_node"; nodeId: string }
  | { kind: "move_node"; nodeId: string; x: number; y: number }
  | { kind: "set_params"; nodeId: string; params: Record<string, unknown>; catalog: Catalog }
  | { kind: "add_edge"; from: string; to: string }
  | { kind: "remove_edge"; edge: GraphEdgeJson }
  | { kind: "select"; nodeId: string | null }
  | { kind: "enter_subgraph"; nodeId: string; paramKey: string }
  | { kind: "exit_subgraph" }        // на уровень вверх
  | { kind: "go_to_level"; depth: number } // клик по крошке
  | { kind: "mark_saved" };

export function initialEditorState(): EditorState {
  return { spec: emptyGraph(), path: [], selection: null, dirty: false };
}

function inCurrent(
  state: EditorState,
  fn: (g: GraphSpecJson) => GraphSpecJson,
): EditorState {
  return {
    ...state,
    spec: updateAtPath(state.spec, state.path, fn),
    dirty: true,
  };
}

export function editorReducer(state: EditorState, a: EditorAction): EditorState {
  switch (a.kind) {
    case "load":
      return {
        spec: normalizeGraph(a.spec),
        path: [],
        selection: null,
        dirty: false,
      };
    case "add_node":
      return inCurrent(state, (g) => addNode(g, a.typeId, a.params, a.x, a.y));
    case "remove_node": {
      const next = inCurrent(state, (g) => removeNode(g, a.nodeId));
      return state.selection === a.nodeId
        ? { ...next, selection: null }
        : next;
    }
    case "move_node":
      return inCurrent(state, (g) => moveNode(g, a.nodeId, a.x, a.y));
    case "set_params":
      return inCurrent(state, (g) => setParams(g, a.nodeId, a.params, a.catalog));
    case "add_edge":
      return inCurrent(state, (g) => addEdge(g, a.from, a.to));
    case "remove_edge":
      return inCurrent(state, (g) => removeEdge(g, a.edge));
    case "select":
      return { ...state, selection: a.nodeId };
    case "enter_subgraph":
      return {
        ...state,
        path: [...state.path, { nodeId: a.nodeId, paramKey: a.paramKey }],
        selection: null,
      };
    case "exit_subgraph":
      return state.path.length === 0
        ? state
        : { ...state, path: state.path.slice(0, -1), selection: null };
    case "go_to_level":
      return { ...state, path: state.path.slice(0, a.depth), selection: null };
    case "mark_saved":
      return { ...state, dirty: false };
  }
}

// ─── Контекст ────────────────────────────────────────────────────────────

interface EditorContextValue {
  state: EditorState;
  dispatch: Dispatch<EditorAction>;
  /** Текущий (видимый) подграф — вычисляется из spec+path, не хранится. */
  current: GraphSpecJson;
}

const EditorContext = createContext<EditorContextValue | null>(null);

export function EditorProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(editorReducer, undefined, initialEditorState);
  const current = useMemo(
    () => getSubgraph(state.spec, state.path),
    [state.spec, state.path],
  );
  const value = useMemo(
    () => ({ state, dispatch, current }),
    [state, current],
  );
  return <EditorContext.Provider value={value}>{children}</EditorContext.Provider>;
}

export function useEditor(): EditorContextValue {
  const ctx = useContext(EditorContext);
  if (!ctx) throw new Error("useEditor вне EditorProvider");
  return ctx;
}
