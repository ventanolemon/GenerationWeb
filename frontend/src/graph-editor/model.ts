// Чистая модель граф-документа — TS-зеркало core/graph/document.py
// (GraphDocument десктопа). Ни одной ссылки на React: только иммутабельные
// функции над GraphSpecJson. Это КЛЮЧЕВОЕ решение модели состояния:
//
//   Источник правды = сам проводной JSON (GraphSpec.to_dict()-совместимый).
//   Тело repeat/map — вложенный GraphSpecJson в params.body, т.е. рекурсия
//   держится ДАННЫМИ, а не спец-случаем редактора. Любая правка внутри тела —
//   это иммутабельное обновление корневого JSON по пути (updateAtPath), как
//   на десктопе тело «сериализуется в params["body"] при каждой правке».
//
//   Следствия: сохранение = отдать состояние как есть (нечему расходиться);
//   открытие/закрытие подграфа не копирует данные (правки видны снаружи
//   немедленно); undo/redo в будущем — история одного значения.
//
// Экранные позиции — meta.layout = {node_id: [x, y]}, движок их игнорирует.

import type {
  Catalog,
  CatalogNode,
  GraphEdgeJson,
  GraphNodeJson,
  GraphPath,
  GraphSpecJson,
  PortDef,
} from "./types";

// ─── Конструкторы ────────────────────────────────────────────────────────

export function emptyGraph(): GraphSpecJson {
  return {
    version: 1,
    nodes: [],
    edges: [],
    meta: { max_attempts: 100, seed: null, layout: {} },
  };
}

/** Нормализовать загруженный из БД граф (params/meta/layout могут отсутствовать). */
export function normalizeGraph(raw: unknown): GraphSpecJson {
  const g = (raw ?? {}) as Partial<GraphSpecJson>;
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const edges = Array.isArray(g.edges) ? g.edges : [];
  const meta: Record<string, unknown> =
    g.meta && typeof g.meta === "object" ? { ...g.meta } : {};
  if (meta.max_attempts == null) meta.max_attempts = 100;
  if (!("seed" in meta)) meta.seed = null;
  // Раскладка: недостающим узлам — позиции сеткой (как GraphDocument.auto_pos).
  const layout: Record<string, [number, number]> = {};
  const rawLayout = meta.layout;
  nodes.forEach((n, i) => {
    const pos =
      rawLayout && typeof rawLayout === "object"
        ? (rawLayout as Record<string, unknown>)[n.id]
        : undefined;
    if (Array.isArray(pos) && pos.length === 2) {
      layout[n.id] = [Number(pos[0]) || 0, Number(pos[1]) || 0];
    } else {
      layout[n.id] = autoPos(i);
    }
  });
  meta.layout = layout;
  return { version: g.version ?? 1, nodes, edges, meta };
}

export function autoPos(index: number): [number, number] {
  const cols = 4, dx = 230, dy = 150, x0 = 40, y0 = 40;
  const row = Math.floor(index / cols);
  const col = index % cols;
  return [x0 + col * dx, y0 + row * dy];
}

// ─── Адресация подграфов ─────────────────────────────────────────────────

/** Подграф по пути от корня (тело repeat/map лежит в params[paramKey]). */
export function getSubgraph(root: GraphSpecJson, path: GraphPath): GraphSpecJson {
  let g = root;
  for (const ref of path) {
    const node = g.nodes.find((n) => n.id === ref.nodeId);
    const body = node?.params?.[ref.paramKey];
    if (!body || typeof body !== "object") {
      // Путь устарел (узел удалён и т.п.) — отдать пустой граф, не падать.
      return emptyGraph();
    }
    g = normalizeGraph(body);
  }
  return g;
}

/**
 * Иммутабельно применить fn к подграфу по пути и вернуть новый корень.
 * Structural sharing: пересоздаются только узлы вдоль пути.
 */
export function updateAtPath(
  root: GraphSpecJson,
  path: GraphPath,
  fn: (g: GraphSpecJson) => GraphSpecJson,
): GraphSpecJson {
  if (path.length === 0) return fn(root);
  const [head, ...rest] = path;
  return {
    ...root,
    nodes: root.nodes.map((n) => {
      if (n.id !== head.nodeId) return n;
      const body = normalizeGraph(n.params?.[head.paramKey]);
      return {
        ...n,
        params: {
          ...(n.params ?? {}),
          [head.paramKey]: updateAtPath(body, rest, fn),
        },
      };
    }),
  };
}

// ─── Мутации (все — чистые, над одним уровнем) ───────────────────────────

export function uniqueId(g: GraphSpecJson, typeId: string): string {
  const taken = new Set(g.nodes.map((n) => n.id));
  let i = 1;
  while (taken.has(`${typeId}_${i}`)) i++;
  return `${typeId}_${i}`;
}

export function addNode(
  g: GraphSpecJson,
  typeId: string,
  params: Record<string, unknown>,
  x: number,
  y: number,
): GraphSpecJson {
  const id = uniqueId(g, typeId);
  const layout = { ...layoutOf(g), [id]: [x, y] as [number, number] };
  return {
    ...g,
    nodes: [...g.nodes, { id, type: typeId, params }],
    meta: { ...g.meta, layout },
  };
}

export function removeNode(g: GraphSpecJson, nodeId: string): GraphSpecJson {
  const layout = { ...layoutOf(g) };
  delete layout[nodeId];
  return {
    ...g,
    nodes: g.nodes.filter((n) => n.id !== nodeId),
    edges: g.edges.filter((e) => {
      const [fn] = e.from.split(":");
      const [tn] = e.to.split(":");
      return fn !== nodeId && tn !== nodeId;
    }),
    meta: { ...g.meta, layout },
  };
}

export function moveNode(
  g: GraphSpecJson, nodeId: string, x: number, y: number,
): GraphSpecJson {
  return {
    ...g,
    meta: { ...g.meta, layout: { ...layoutOf(g), [nodeId]: [x, y] } },
  };
}

/** Заменить параметры узла + обрезать рёбра на исчезнувшие порты
 * (как GraphDocument.prune_invalid_edges после правки в инспекторе). */
export function setParams(
  g: GraphSpecJson,
  nodeId: string,
  params: Record<string, unknown>,
  catalog: Catalog,
): GraphSpecJson {
  const next = {
    ...g,
    nodes: g.nodes.map((n) => (n.id === nodeId ? { ...n, params } : n)),
  };
  return pruneInvalidEdges(next, catalog);
}

/** Провод: один на вход — существующий в (to) вытесняется (как на десктопе). */
export function addEdge(
  g: GraphSpecJson, from: string, to: string,
): GraphSpecJson {
  return {
    ...g,
    edges: [...g.edges.filter((e) => e.to !== to), { from, to }],
  };
}

export function removeEdge(g: GraphSpecJson, edge: GraphEdgeJson): GraphSpecJson {
  return {
    ...g,
    edges: g.edges.filter((e) => !(e.from === edge.from && e.to === edge.to)),
  };
}

export function pruneInvalidEdges(g: GraphSpecJson, catalog: Catalog): GraphSpecJson {
  const inPorts = new Map<string, Set<string>>();
  const outPorts = new Map<string, Set<string>>();
  for (const n of g.nodes) {
    const { inputs, outputs } = derivePorts(catalog, n);
    inPorts.set(n.id, new Set(inputs.map((p) => p.name)));
    outPorts.set(n.id, new Set(outputs.map((p) => p.name)));
  }
  const edges = g.edges.filter((e) => {
    const [fn, fp] = e.from.split(":");
    const [tn, tp] = e.to.split(":");
    return outPorts.get(fn)?.has(fp) && inPorts.get(tn)?.has(tp);
  });
  return edges.length === g.edges.length ? g : { ...g, edges };
}

export function layoutOf(g: GraphSpecJson): Record<string, [number, number]> {
  const raw = g.meta?.layout;
  return raw && typeof raw === "object"
    ? (raw as Record<string, [number, number]>)
    : {};
}

export function nodePos(g: GraphSpecJson, nodeId: string): [number, number] {
  return layoutOf(g)[nodeId] ?? [40, 40];
}

// ─── Динамические порты ──────────────────────────────────────────────────
//
// Каталог отдаёт СТАТИЧЕСКИЙ шаблон портов класса; у части узлов порты
// зависят от params. Контракт (§2) разрешает клиенту «реализовать те же
// правила портов локально по params_schema (как десктоп)» — здесь TS-зеркало
// правил input_ports()/output_ports() из core/graph/nodes/* для узлов,
// нужных скелету. Для остальных — статический шаблон из каталога
// (тот же откат, что GraphDocument.safe_ports).

const FORMULA_FUNCS = new Set([
  "abs", "acos", "asin", "atan", "ceil", "cos", "exp", "floor", "ln", "log",
  "log10", "log2", "round", "sin", "sqrt", "tan",
]);
// Известный footgun языка: эти буквы в formula — физические константы.
const FORMULA_CONSTS = new Set([
  "pi", "π", "e", "g", "G", "c", "h", "k_B", "N_A", "R_g",
]);

/** Имена переменных формулы: идентификаторы минус функции и константы. */
function formulaVarNames(expr: string): string[] {
  const ids = expr.match(/[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*/g) ?? [];
  const seen = new Set<string>();
  for (const id of ids) {
    if (!FORMULA_FUNCS.has(id) && !FORMULA_CONSTS.has(id)) seen.add(id);
  }
  return [...seen].sort();
}

/** Маркеры #имя# в порядке появления (зеркало _marker_names). */
function markerNames(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const m of text.matchAll(/#([^#\s]+)#/g)) {
    if (!seen.has(m[1])) {
      seen.add(m[1]);
      out.push(m[1]);
    }
  }
  return out;
}

/** Разбор 'имя:тип' у imports (тип по умолчанию number). */
function parseImports(params: Record<string, unknown> | undefined): PortDef[] {
  const raw = params?.imports;
  if (!Array.isArray(raw)) return [];
  const out: PortDef[] = [];
  for (const item of raw) {
    const s = String(item).trim();
    if (!s) continue;
    const [name, tname] = s.split(":").map((p) => p.trim());
    if (name) out.push({ name, type: tname || "number", required: false });
  }
  return out;
}

/** Разбор 'имя[:тип[:режим]]' у outputs → внешний порт туннеля. */
function parseOutputTunnels(params: Record<string, unknown> | undefined): PortDef[] {
  const raw = params?.outputs;
  if (!Array.isArray(raw)) return [];
  const out: PortDef[] = [];
  for (const item of raw) {
    const s = String(item).trim();
    if (!s) continue;
    const parts = s.split(":").map((p) => p.trim());
    const name = parts[0];
    const tname = parts[1] || "number";
    const mode = parts[2] || "list";
    if (!name || name === "out") continue;
    // Режим list = индексированный сбор: блоки → block_list, прочее → list.
    const type =
      mode === "last" ? tname : tname === "block" ? "block_list" : "list";
    out.push({ name, type, required: false });
  }
  return out;
}

/** Разбор 'имя:тип:начальное' у registers → выходы reg_<имя>. */
function parseRegisters(params: Record<string, unknown> | undefined): PortDef[] {
  const raw = params?.registers;
  if (!Array.isArray(raw)) return [];
  const out: PortDef[] = [];
  for (const item of raw) {
    const s = String(item).trim();
    if (!s) continue;
    const parts = s.split(":").map((p) => p.trim());
    if (parts[0]) {
      out.push({ name: `reg_${parts[0]}`, type: parts[1] || "number", required: false });
    }
  }
  return out;
}

const VARS_PORT: PortDef = { name: "vars", type: "number_dict", required: false };

export function catalogNode(catalog: Catalog, typeId: string): CatalogNode | undefined {
  return catalog.nodes.find((n) => n.type_id === typeId);
}

export function derivePorts(
  catalog: Catalog,
  node: GraphNodeJson,
): { inputs: PortDef[]; outputs: PortDef[] } {
  const cn = catalogNode(catalog, node.type);
  const staticIn: PortDef[] = cn ? [...cn.inputs] : [];
  const staticOut: PortDef[] = cn ? [...cn.outputs] : [];
  const p = node.params ?? {};

  switch (node.type) {
    case "formula":
      return {
        inputs: [
          ...formulaVarNames(String(p.expr ?? "")).map((n) => ({
            name: n, type: "number", required: false,
          })),
          VARS_PORT,
        ],
        outputs: staticOut,
      };
    case "text":
    case "template":
      return {
        inputs: [
          ...markerNames(String(p.text ?? "")).map((n) => ({
            name: n, type: "any", required: false,
          })),
          VARS_PORT,
        ],
        outputs: staticOut,
      };
    case "var_dict": {
      const names = Array.isArray(p.names) ? p.names.map(String) : [];
      return {
        inputs: names.map((n) => ({ name: n, type: "number", required: true })),
        outputs: staticOut,
      };
    }
    case "block_list": {
      const count = Math.max(1, Number(p.count ?? 1) || 1);
      return {
        inputs: Array.from({ length: count }, (_, i) => ({
          name: `in${i}`, type: "block", required: false,
        })),
        outputs: staticOut,
      };
    }
    case "repeat":
      return {
        inputs: [
          { name: "count", type: "number", required: false },
          ...parseImports(p),
        ],
        outputs: [
          { name: "out", type: "block_list", required: false },
          ...parseOutputTunnels(p),
          ...parseRegisters(p),
        ],
      };
    case "map":
      return {
        inputs: [
          { name: "items", type: "list", required: true },
          ...parseImports(p),
        ],
        outputs: [
          { name: "out", type: "block_list", required: false },
          ...parseOutputTunnels(p),
        ],
      };
    default:
      // Статический шаблон каталога — как откат safe_ports на десктопе.
      // (case/select/random_choice и пр. доопределит следующий этап.)
      return { inputs: staticIn, outputs: staticOut };
  }
}

// ─── Совместимость портов (зеркало port_types.is_compatible) ─────────────

export function isCompatible(src: string, dst: string): boolean {
  if (src === dst) return true;
  if (src === "any" || dst === "any") return true;
  if (src === "block" && dst === "block_list") return true;
  if (src === "number" && dst === "expr") return true;
  return false;
}

/** Есть ли одноузловый конвертер src→dst (для янтарной подсветки). */
export function findConverter(
  catalog: Catalog, src: string, dst: string,
): string | null {
  const c = catalog.conversions.find((x) => x.from === src && x.to === dst);
  return c ? c.via : null;
}

// ─── Финальный узел (бейдж «ВЫХОД», зеркало task_sink_ids) ───────────────

export function taskSinkIds(catalog: Catalog, g: GraphSpecJson): string[] {
  const consumed = new Set(g.edges.map((e) => e.from));
  return g.nodes
    .filter((n) =>
      derivePorts(catalog, n).outputs.some(
        (o) => o.type === "task" && !consumed.has(`${n.id}:${o.name}`),
      ),
    )
    .map((n) => n.id);
}

/** Есть ли у типа узла выход TASK (запрет в подграфах — инвариант языка). */
export function typeHasTaskOutput(catalog: Catalog, typeId: string): boolean {
  const cn = catalogNode(catalog, typeId);
  return !!cn?.outputs.some((o) => o.type === "task");
}

// ─── Сериализация ────────────────────────────────────────────────────────

/**
 * Проводная форма для validate/preview/сохранения: ровно GraphSpec.to_dict().
 * Состояние УЖЕ в этой форме — только гарантируем version и что params
 * присутствует объектом (парсер ядра принимает отсутствие, но единообразие
 * дешевле): ничего не перепаковываем.
 */
export function toWire(g: GraphSpecJson): GraphSpecJson {
  return {
    version: g.version ?? 1,
    nodes: g.nodes.map((n) => ({
      id: n.id, type: n.type, params: n.params ?? {},
    })),
    edges: g.edges,
    meta: g.meta,
  };
}
