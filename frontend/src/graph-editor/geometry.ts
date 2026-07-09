// Геометрия узлов и портов. Позиции портов считаются из констант (детермини-
// рованная сетка), а не измерением DOM — провода и хит-тесты не зависят от
// момента рендера.

import type { Catalog, GraphNodeJson, GraphSpecJson, PortDef } from "./types";
import { derivePorts, nodePos } from "./model";

export const NODE_W = 176;
export const HEADER_H = 26;
export const ROW_H = 20;
export const BODY_PAD = 6;

export function nodeHeight(nIn: number, nOut: number): number {
  return HEADER_H + BODY_PAD * 2 + Math.max(nIn, nOut, 1) * ROW_H;
}

export function portY(index: number): number {
  return HEADER_H + BODY_PAD + index * ROW_H + ROW_H / 2;
}

export interface PortPoint {
  x: number;
  y: number;
  port: PortDef;
}

/** Мировые координаты центра точки порта. side: вход слева, выход справа. */
export function portPoint(
  catalog: Catalog,
  g: GraphSpecJson,
  node: GraphNodeJson,
  portName: string,
  side: "in" | "out",
): PortPoint | null {
  const [x, y] = nodePos(g, node.id);
  const { inputs, outputs } = derivePorts(catalog, node);
  const list = side === "in" ? inputs : outputs;
  const idx = list.findIndex((p) => p.name === portName);
  if (idx < 0) return null;
  return {
    x: side === "in" ? x : x + NODE_W,
    y: y + portY(idx),
    port: list[idx],
  };
}

/** Цвета проводов по типу порта — та же роль, что цветовая легенда десктопа. */
export const PORT_COLORS: Record<string, string> = {
  number: "#4f9dde",
  string: "#8ab861",
  number_dict: "#c78f3f",
  bool: "#d46a6a",
  list: "#b085c9",
  expr: "#b455b4",
  matrix: "#5c6bc0",
  image: "#26a69a",
  words: "#00897b",
  sentences: "#00acc1",
  block: "#e0a030",
  block_list: "#e07a30",
  task: "#43a047",
  func: "#7e57c2",
  any: "#9e9e9e",
};

export function portColor(type: string): string {
  return PORT_COLORS[type] ?? "#9e9e9e";
}

/** Кубический безье слева-направо (простые провода — по брифу достаточно). */
export function wirePath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = Math.max(40, Math.abs(x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}
