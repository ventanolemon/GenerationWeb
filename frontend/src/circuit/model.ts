// Схема как данные: узлы, соединения, раскладка и формула.
//
// Отдельно от компонента намеренно. Здесь нет ни React, ни SVG — только
// то, что можно проверить тестом: можно ли подключить этот выход к
// этому входу, что получится за формула, где рисовать элемент. Именно
// это и есть содержательная часть холста; всё остальное — прямоугольники.
//
// Граница «холст ↔ семантика» (interactive_tasks_plan, §7.3) проходит
// здесь же: модуль знает про элементы, якоря и соединения — и ничего про
// проверку ответа. Формула уезжает строкой в том же виде, в каком её
// печатает генератор схем (`not(A) v (B ^ C)`), а сравнивает ФУНКЦИИ уже
// ядро. Поэтому холст не пришлось встраивать в проверку: он просто
// собирает ответ, который и так умеют проверять.

export type GateType = "INPUT" | "AND" | "OR" | "NOT";

export interface Node {
  id: string;
  type: GateType;
  /** Имя входа схемы. Только у INPUT. */
  name?: string;
  /** Идентификаторы источников. Пусто у INPUT. */
  inputs: string[];
}

/** Сколько входов требует вентиль. INPUT — ноль, NOT — один, И/ИЛИ — два. */
export function arity(type: GateType): number {
  if (type === "INPUT") return 0;
  return type === "NOT" ? 1 : 2;
}

/** Подпись элемента по ГОСТ 2.743-91: «&» у И, «1» у ИЛИ и НЕ. */
export function glyph(node: Node): string {
  if (node.type === "INPUT") return node.name ?? "?";
  return node.type === "AND" ? "&" : "1";
}

export function inputs(variables: string[]): Node[] {
  return variables.map((name) => ({ id: `in:${name}`, type: "INPUT", name, inputs: [] }));
}

let counter = 0;

export function newGate(type: GateType): Node {
  counter += 1;
  return { id: `g${counter}`, type, inputs: [] };
}

/** Для тестов: сделать нумерацию предсказуемой. */
export function resetIds(): void {
  counter = 0;
}

export function byId(nodes: Node[], id: string): Node | undefined {
  return nodes.find((n) => n.id === id);
}

/**
 * Достижим ли `target` из `from` по проводам.
 *
 * Нужно для запрета петель: соединение, замыкающее цикл, превращает
 * схему в нечто, у чего нет функции, — а узнать об этом по чертежу
 * студент не сможет, потому что рисуется он одинаково.
 */
export function reaches(nodes: Node[], from: string, target: string): boolean {
  const seen = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const id = stack.pop()!;
    if (id === target) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    const node = byId(nodes, id);
    if (node) stack.push(...node.inputs);
  }
  return false;
}

/** Можно ли подать выход `sourceId` на вход `slot` вентиля `gateId`. */
export function canConnect(
  nodes: Node[],
  sourceId: string,
  gateId: string,
  slot: number,
): boolean {
  const gate = byId(nodes, gateId);
  const source = byId(nodes, sourceId);
  if (!gate || !source || gate.type === "INPUT") return false;
  if (sourceId === gateId) return false;
  if (slot < 0 || slot >= arity(gate.type)) return false;
  // Один и тот же источник дважды на один вентиль — это не схема, а
  // ошибка чертежа: `A & A` рисуется двумя проводами и значит `A`.
  if (gate.inputs.some((id, i) => id === sourceId && i !== slot)) return false;
  // Провод назад по цепи замкнул бы петлю.
  return !reaches(nodes, sourceId, gateId);
}

export function connect(
  nodes: Node[],
  sourceId: string,
  gateId: string,
  slot: number,
): Node[] {
  if (!canConnect(nodes, sourceId, gateId, slot)) return nodes;
  return nodes.map((node) => {
    if (node.id !== gateId) return node;
    const next = [...node.inputs];
    while (next.length < arity(node.type)) next.push("");
    next[slot] = sourceId;
    return { ...node, inputs: next };
  });
}

export function disconnect(nodes: Node[], gateId: string, slot: number): Node[] {
  return nodes.map((node) => {
    if (node.id !== gateId) return node;
    const next = [...node.inputs];
    if (slot < next.length) next[slot] = "";
    return { ...node, inputs: next };
  });
}

/** Убрать вентиль и все провода, которые в него шли. */
export function remove(nodes: Node[], gateId: string): Node[] {
  return nodes
    .filter((node) => node.id !== gateId)
    .map((node) => ({
      ...node,
      inputs: node.inputs.map((id) => (id === gateId ? "" : id)),
    }));
}

/** Узлы, выход которых никуда не идёт. */
export function unused(nodes: Node[]): Node[] {
  const consumed = new Set(nodes.flatMap((n) => n.inputs).filter(Boolean));
  return nodes.filter((n) => !consumed.has(n.id));
}

export interface Problem {
  text: string;
  nodeId?: string;
}

/**
 * Чего не хватает до готовой схемы.
 *
 * Список, а не булев признак: студенту надо сказать, ЧТО доделать, иначе
 * заблокированная кнопка «Ответить» выглядит поломкой. Порядок — от
 * общего к частному, показывается первая проблема.
 */
export function problems(nodes: Node[], variables: string[]): Problem[] {
  const out: Problem[] = [];

  for (const node of nodes) {
    const need = arity(node.type);
    for (let slot = 0; slot < need; slot += 1) {
      if (!node.inputs[slot]) {
        out.push({ text: "У вентиля не подключены все входы.", nodeId: node.id });
        break;
      }
    }
  }

  const ends = unused(nodes).filter((n) => n.type !== "INPUT");
  if (nodes.every((n) => n.type === "INPUT")) {
    out.push({ text: "Схема пуста: добавьте хотя бы один вентиль." });
  } else if (ends.length > 1) {
    out.push({ text: "У схемы больше одного выхода — соедините ветви." });
  } else if (ends.length === 0) {
    out.push({ text: "У схемы нет выхода." });
  } else {
    // Вход, не дотянувшийся до выхода, нарисован и ни на что не влияет —
    // ровно тот дефект, который нашёлся в самом генераторе схем (§2.5).
    // Раз он считается ошибкой у генератора, то и у студента тоже.
    const reachable = reachableFrom(nodes, ends[0].id);
    for (const name of variables) {
      if (!reachable.has(`in:${name}`)) {
        out.push({ text: `Вход ${name} ни к чему не подключён.`, nodeId: `in:${name}` });
      }
    }
  }
  return out;
}

function reachableFrom(nodes: Node[], id: string): Set<string> {
  const seen = new Set<string>();
  const stack = [id];
  while (stack.length) {
    const current = stack.pop()!;
    if (seen.has(current)) continue;
    seen.add(current);
    const node = byId(nodes, current);
    if (node) stack.push(...node.inputs.filter(Boolean));
  }
  return seen;
}

/** Выход схемы или null, если схема ещё не готова. */
export function output(nodes: Node[]): Node | null {
  const ends = unused(nodes).filter((n) => n.type !== "INPUT");
  return ends.length === 1 ? ends[0] : null;
}

/**
 * Формула в обозначениях схемы: `not(A) v (B ^ C)`.
 *
 * Та же запись, что печатает генератор под чертежом, и та же, которую
 * читает проверка. Совпадение не случайно: холст отвечает ТЕМ ЖЕ, что
 * студент написал бы руками, поэтому проверять его не нужно ничем
 * особенным.
 */
export function formula(nodes: Node[], id: string): string {
  const node = byId(nodes, id);
  if (!node) return "";
  if (node.type === "INPUT") return node.name ?? "";
  if (node.type === "NOT") return `not(${formula(nodes, node.inputs[0])})`;
  const sign = node.type === "AND" ? " ^ " : " v ";
  return `(${node.inputs.map((child) => formula(nodes, child)).join(sign)})`;
}

/** Формула всей схемы или пустая строка, если она не готова. */
export function answer(nodes: Node[]): string {
  const end = output(nodes);
  return end ? formula(nodes, end.id) : "";
}

// ─── Раскладка ───────────────────────────────────────────────────────────

export interface Placed {
  node: Node;
  x: number;
  y: number;
}

export const GEOMETRY = {
  gateWidth: 54,
  gateHeight: 42,
  columnGap: 96,
  rowGap: 60,
  padding: 28,
};

/**
 * Координаты элементов: столбец = глубина, строка = порядок внутри.
 *
 * Глубина считается как ДЛИННЕЙШИЙ путь от входов, а не кратчайший:
 * иначе вентиль, у которого один вход идёт от входа схемы, а другой — из
 * третьего слоя, встал бы слева от своего источника, и провод пошёл бы
 * назад.
 */
export function layout(nodes: Node[]): Placed[] {
  const depth = new Map<string, number>();
  const compute = (id: string, guard: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (guard.has(id)) return 0;
    guard.add(id);
    const node = byId(nodes, id);
    const value = !node || node.inputs.length === 0
      ? 0
      : 1 + Math.max(...node.inputs.filter(Boolean).map((child) => compute(child, guard)), 0);
    depth.set(id, value);
    return value;
  };
  nodes.forEach((node) => compute(node.id, new Set()));

  const columns = new Map<number, Node[]>();
  nodes.forEach((node) => {
    const level = depth.get(node.id) ?? 0;
    columns.set(level, [...(columns.get(level) ?? []), node]);
  });

  const out: Placed[] = [];
  const tallest = Math.max(...[...columns.values()].map((c) => c.length), 1);
  [...columns.keys()].sort((a, b) => a - b).forEach((level) => {
    const column = columns.get(level)!;
    const offset = (tallest - column.length) / 2;
    column.forEach((node, index) => {
      out.push({
        node,
        x: GEOMETRY.padding + level * GEOMETRY.columnGap,
        y: GEOMETRY.padding + (offset + index) * GEOMETRY.rowGap,
      });
    });
  });
  return out;
}

export function canvasSize(placed: Placed[]): { width: number; height: number } {
  const width = Math.max(...placed.map((p) => p.x), 0)
    + GEOMETRY.gateWidth + GEOMETRY.columnGap;
  const height = Math.max(...placed.map((p) => p.y), 0)
    + GEOMETRY.gateHeight + GEOMETRY.padding;
  return { width, height };
}
