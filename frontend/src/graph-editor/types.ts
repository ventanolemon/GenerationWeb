// Типы граф-редактора: зеркало проводного формата GraphSpec.to_dict()
// (docs/architecture/graph_editor_api_contract.md §1) и каталога §2.
//
// ИНВАРИАНТ: GraphSpecJson — ровно то, что уходит в generation_params
// партиции constracted=4 и что исполняет core/graph. Экранные координаты —
// только в meta.layout (движок их игнорирует), никаких «веб-полей» вне meta.

// ─── Проводной формат графа ──────────────────────────────────────────────

export interface GraphNodeJson {
  id: string;
  type: string;
  params?: Record<string, unknown>;
}

export interface GraphEdgeJson {
  from: string; // "node:port"
  to: string;   // "node:port"
}

export interface GraphSpecJson {
  version?: number;
  nodes: GraphNodeJson[];
  edges: GraphEdgeJson[];
  meta: Record<string, unknown>;
}

// ─── Каталог узлов (GET /graph/catalog) ──────────────────────────────────

export interface CatalogPort {
  name: string;
  type: string;      // id PortType: "number" | "string" | "block" | ...
  required: boolean;
}

export interface CatalogNode {
  type_id: string;
  category: string;
  display_name: string;
  description: string;
  inputs: CatalogPort[];
  outputs: CatalogPort[];
  // Дословный PARAMS_SCHEMA узла: {имя: {type, default?, optional?, values?}}
  params_schema: Record<string, ParamSchema>;
}

export interface ParamSchema {
  type: string; // string | text | int | number | bool | enum | list | subgraph | file | hidden
  default?: unknown;
  optional?: boolean;
  values?: string[];
}

export interface CatalogConversion {
  from: string;
  to: string;
  via: string; // type_id узла-конвертера
}

export interface Catalog {
  catalog_version: string;
  port_types: { id: string }[];
  conversions: CatalogConversion[];
  nodes: CatalogNode[];
}

// ─── Ответы validate / preview ───────────────────────────────────────────

export interface ValidateResponse {
  ok: boolean;
  errors: string[];
  result_node: string | null;
  catalog_version: string;
}

export interface PreviewRun {
  seed: number;
  statement: unknown[]; // BlockJSON — рендерится существующим BlockRenderer
  answer: unknown[];
  attempts: number;
  wall_ms: number;
  error: string | null;
}

export interface PreviewResponse {
  ok: boolean;
  errors: string[];
  runs: PreviewRun[];
}

// ─── Адресация вложенных подграфов ───────────────────────────────────────
//
// Тело repeat/map — вложенный GraphSpecJson в params[paramKey] узла.
// Путь от корня — стек таких ссылок; вся навигация редактора («открыть тело
// цикла», хлебные крошки) — это ровно путь в ДАННЫЕ, а не отдельная копия
// подграфа в состоянии редактора.

export interface SubgraphRef {
  nodeId: string;
  paramKey: string; // "body" у repeat/map; "case_0"/"default" у case
}

export type GraphPath = SubgraphRef[];

// Порт, вычисленный для конкретного узла (с учётом динамических правил).
export interface PortDef {
  name: string;
  type: string;
  required: boolean;
}
