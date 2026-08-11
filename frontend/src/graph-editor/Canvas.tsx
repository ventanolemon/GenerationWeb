// Холст: панорама/зум, перетаскивание узлов, протяжка проводов с проверкой
// типов (зелёный — совместимо, янтарный — есть конвертер), выделение и
// удаление. Провода — простые безье (ортогональная трассировка — отдельный
// трек, вне скелета).

import { useMemo, useRef, useState } from "react";
import type { Catalog, GraphEdgeJson } from "./types";
import { useEditor } from "./store";
import {
  branchMap,
  catalogNode,
  derivePorts,
  edgeKey,
  edgeNote,
  findConverter,
  isCompatible,
  nodePos,
  taskSinkIds,
} from "./model";
import {
  BRANCH_COLORS,
  BRANCH_UNUSED,
  portColor,
  portPoint,
  wireMidpoint,
  wirePath,
} from "./geometry";
import NodeItem from "./NodeItem";
import styles from "../styles/graph-editor.module.css";

interface Props {
  catalog: Catalog;
  /** Статус-строка холста (подсказки «нужен конвертер …»). */
  onStatus: (text: string) => void;
}

interface WireDrag {
  nodeId: string;
  port: string;
  side: "in" | "out";
  type: string;
  x: number; // мировые координаты курсора
  y: number;
}

type DragState =
  | { kind: "pan"; startX: number; startY: number; panX: number; panY: number }
  | { kind: "node"; nodeId: string; offX: number; offY: number }
  | { kind: "wire"; wire: WireDrag }
  | null;

export default function Canvas({ catalog, onStatus }: Props) {
  const { state, dispatch, current } = useEditor();
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [pan, setPan] = useState({ x: 20, y: 20 });
  const [zoom, setZoom] = useState(1);
  const [drag, setDrag] = useState<DragState>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdgeJson | null>(null);
  // Подсветка веток — режим ЧТЕНИЯ, поэтому включается, а не живёт всегда:
  // при разводке проводов нужнее цвет типа порта, при разборе чужого графа —
  // «что готовит условие, а что ответ». Совмещать оба в одном цвете нельзя.
  const [showBranches, setShowBranches] = useState(false);

  const sinks = useMemo(() => taskSinkIds(catalog, current), [catalog, current]);
  const branches = useMemo(
    () => (showBranches ? branchMap(catalog, current) : null),
    [showBranches, catalog, current],
  );

  function toWorld(e: { clientX: number; clientY: number }): [number, number] {
    const rect = viewportRef.current!.getBoundingClientRect();
    return [
      (e.clientX - rect.left - pan.x) / zoom,
      (e.clientY - rect.top - pan.y) / zoom,
    ];
  }

  // ─── Фон: панорама и сброс выделения ───────────────────────────────────

  function onBackgroundMouseDown(e: React.MouseEvent) {
    if (e.target !== e.currentTarget) return;
    dispatch({ kind: "select", nodeId: null });
    setSelectedEdge(null);
    setDrag({
      kind: "pan",
      startX: e.clientX, startY: e.clientY,
      panX: pan.x, panY: pan.y,
    });
  }

  function onMouseMove(e: React.MouseEvent) {
    if (!drag) return;
    if (drag.kind === "pan") {
      setPan({
        x: drag.panX + (e.clientX - drag.startX),
        y: drag.panY + (e.clientY - drag.startY),
      });
    } else if (drag.kind === "node") {
      const [wx, wy] = toWorld(e);
      dispatch({
        kind: "move_node",
        nodeId: drag.nodeId,
        x: Math.round(wx - drag.offX),
        y: Math.round(wy - drag.offY),
      });
    } else if (drag.kind === "wire") {
      const [wx, wy] = toWorld(e);
      setDrag({ kind: "wire", wire: { ...drag.wire, x: wx, y: wy } });
    }
  }

  function onMouseUp() {
    if (drag?.kind === "wire") onStatus("");
    setDrag(null);
  }

  function onWheel(e: React.WheelEvent) {
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    const next = Math.min(2.5, Math.max(0.25, zoom * factor));
    if (next === zoom) return;
    // Зум к курсору: точка под курсором остаётся на месте.
    const rect = viewportRef.current!.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    setPan({
      x: cx - ((cx - pan.x) / zoom) * next,
      y: cy - ((cy - pan.y) / zoom) * next,
    });
    setZoom(next);
  }

  // ─── Узлы ──────────────────────────────────────────────────────────────

  function onNodeHeaderMouseDown(nodeId: string, e: React.MouseEvent) {
    e.stopPropagation();
    dispatch({ kind: "select", nodeId });
    setSelectedEdge(null);
    const [wx, wy] = toWorld(e);
    const [nx, ny] = nodePos(current, nodeId);
    setDrag({ kind: "node", nodeId, offX: wx - nx, offY: wy - ny });
  }

  function onNodeDoubleClick(nodeId: string) {
    // Двойной клик по узлу с подграфом — открыть тело (repeat/map: body).
    const node = current.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const cn = catalogNode(catalog, node.type);
    const key = Object.entries(cn?.params_schema ?? {}).find(
      ([, s]) => s.type === "subgraph",
    )?.[0];
    if (key) dispatch({ kind: "enter_subgraph", nodeId, paramKey: key });
  }

  // ─── Провода ───────────────────────────────────────────────────────────

  function onPortMouseDown(
    nodeId: string, side: "in" | "out", port: string, e: React.MouseEvent,
  ) {
    e.stopPropagation();
    e.preventDefault();
    const node = current.nodes.find((n) => n.id === nodeId)!;
    const pp = portPoint(catalog, current, node, port, side);
    if (!pp) return;
    const [wx, wy] = toWorld(e);
    setDrag({
      kind: "wire",
      wire: { nodeId, port, side, type: pp.port.type, x: wx, y: wy },
    });
  }

  function onPortMouseUp(
    nodeId: string, side: "in" | "out", port: string, e: React.MouseEvent,
  ) {
    if (drag?.kind !== "wire") return;
    e.stopPropagation();
    const w = drag.wire;
    setDrag(null);
    onStatus("");
    if (w.side === side || w.nodeId === nodeId) return; // вход↔выход, не сам в себя
    const from = side === "in" ? w : { nodeId, port, side, type: "" };
    const to = side === "in" ? { nodeId, port } : { nodeId: w.nodeId, port: w.port };
    // Типы: src — тип выхода, dst — тип входа (пересчитать по фактическим узлам).
    const srcNode = current.nodes.find((n) => n.id === from.nodeId)!;
    const dstNode = current.nodes.find((n) => n.id === to.nodeId)!;
    const src = portPoint(catalog, current, srcNode, from.port, "out");
    const dst = portPoint(catalog, current, dstNode, to.port, "in");
    if (!src || !dst) return;
    if (isCompatible(src.port.type, dst.port.type)) {
      dispatch({
        kind: "add_edge",
        from: `${from.nodeId}:${from.port}`,
        to: `${to.nodeId}:${to.port}`,
      });
    } else {
      const via = findConverter(catalog, src.port.type, dst.port.type);
      onStatus(
        via
          ? `Типы ${src.port.type} → ${dst.port.type} несовместимы напрямую — вставьте узел-конвертер «${via}».`
          : `Типы несовместимы: ${src.port.type} → ${dst.port.type}.`,
      );
    }
  }

  /** Подсказки входов при протяжке провода от выхода. */
  function dropHintsFor(nodeId: string): Record<string, "green" | "amber"> | null {
    if (drag?.kind !== "wire" || drag.wire.side !== "out") return null;
    if (drag.wire.nodeId === nodeId) return null;
    const node = current.nodes.find((n) => n.id === nodeId)!;
    const hints: Record<string, "green" | "amber"> = {};
    for (const p of derivePorts(catalog, node).inputs) {
      if (isCompatible(drag.wire.type, p.type)) hints[p.name] = "green";
      else if (findConverter(catalog, drag.wire.type, p.type)) hints[p.name] = "amber";
    }
    return hints;
  }

  // ─── Удаление с клавиатуры ─────────────────────────────────────────────

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== "Delete" && e.key !== "Backspace") return;
    const target = e.target as HTMLElement;
    if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
    if (selectedEdge) {
      dispatch({ kind: "remove_edge", edge: selectedEdge });
      setSelectedEdge(null);
    } else if (state.selection) {
      dispatch({ kind: "remove_node", nodeId: state.selection });
    }
  }

  // ─── Рендер ────────────────────────────────────────────────────────────

  const wires = current.edges.map((e) => {
    const [fn, fp] = e.from.split(":");
    const [tn, tp] = e.to.split(":");
    const srcNode = current.nodes.find((n) => n.id === fn);
    const dstNode = current.nodes.find((n) => n.id === tn);
    if (!srcNode || !dstNode) return null;
    const a = portPoint(catalog, current, srcNode, fp, "out");
    const b = portPoint(catalog, current, dstNode, tp, "in");
    if (!a || !b) return null;
    const isSel =
      selectedEdge && selectedEdge.from === e.from && selectedEdge.to === e.to;
    const branch = branches?.edges.get(edgeKey(e));
    const stroke = isSel
      ? "#ff5252"
      : branches
        ? (branch ? BRANCH_COLORS[branch] : BRANCH_UNUSED)
        : portColor(a.port.type);
    const note = edgeNote(current, e);
    const [mx, my] = wireMidpoint(a.x, a.y, b.x, b.y);
    return (
      <g key={edgeKey(e)}>
        {/* Широкий прозрачный штрих — зона клика */}
        <path
          d={wirePath(a.x, a.y, b.x, b.y)}
          stroke="transparent"
          strokeWidth={12}
          fill="none"
          style={{ cursor: "pointer", pointerEvents: "stroke" }}
          onMouseDown={(ev) => {
            ev.stopPropagation();
            setSelectedEdge(e);
            dispatch({ kind: "select", nodeId: null });
          }}
        />
        <path
          d={wirePath(a.x, a.y, b.x, b.y)}
          stroke={stroke}
          strokeWidth={isSel ? 3 : 2}
          fill="none"
          style={{ pointerEvents: "none" }}
        />
        {note && !isSel && (
          // Подложка под текстом: провод проходит ровно под подписью, и
          // без неё текст читается только на светлых участках холста.
          <text
            className={styles.wireNote}
            x={mx}
            y={my}
            textAnchor="middle"
            dominantBaseline="middle"
            paintOrder="stroke"
            style={{ pointerEvents: "none" }}
          >
            {note}
          </text>
        )}
      </g>
    );
  });

  /** Поле подписи выделенного провода — правка на месте, у самого провода. */
  let noteEditor = null;
  if (selectedEdge) {
    const [fn, fp] = selectedEdge.from.split(":");
    const [tn, tp] = selectedEdge.to.split(":");
    const srcNode = current.nodes.find((n) => n.id === fn);
    const dstNode = current.nodes.find((n) => n.id === tn);
    const a = srcNode && portPoint(catalog, current, srcNode, fp, "out");
    const b = dstNode && portPoint(catalog, current, dstNode, tp, "in");
    if (a && b) {
      const [mx, my] = wireMidpoint(a.x, a.y, b.x, b.y);
      noteEditor = (
        <input
          className={styles.wireNoteInput}
          style={{ left: mx - 80, top: my - 11 }}
          placeholder="подпись провода"
          value={edgeNote(current, selectedEdge)}
          onChange={(ev) =>
            dispatch({
              kind: "set_edge_note",
              edge: selectedEdge,
              text: ev.target.value,
            })
          }
          onMouseDown={(ev) => ev.stopPropagation()}
          onKeyDown={(ev) => {
            if (ev.key === "Escape") setSelectedEdge(null);
            ev.stopPropagation();
          }}
        />
      );
    }
  }

  let tempWire = null;
  if (drag?.kind === "wire") {
    const w = drag.wire;
    const node = current.nodes.find((n) => n.id === w.nodeId);
    const p = node && portPoint(catalog, current, node, w.port, w.side);
    if (p) {
      const [x1, y1, x2, y2] =
        w.side === "out" ? [p.x, p.y, w.x, w.y] : [w.x, w.y, p.x, p.y];
      tempWire = (
        <path
          d={wirePath(x1, y1, x2, y2)}
          stroke={portColor(w.type)}
          strokeWidth={2}
          strokeDasharray="6 4"
          fill="none"
          style={{ pointerEvents: "none" }}
        />
      );
    }
  }

  return (
    <div
      ref={viewportRef}
      className={styles.viewport}
      tabIndex={0}
      onMouseDown={onBackgroundMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
      onWheel={onWheel}
      onKeyDown={onKeyDown}
    >
      <div
        className={styles.world}
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
        }}
      >
        <svg className={styles.wireLayer}>
          {wires}
          {tempWire}
        </svg>
        {noteEditor}
        {current.nodes.map((n) => {
          const [x, y] = nodePos(current, n.id);
          return (
            <NodeItem
              key={n.id}
              catalog={catalog}
              node={n}
              x={x}
              y={y}
              selected={state.selection === n.id}
              branch={branches ? branches.nodes.get(n.id) ?? "unused" : null}
              sinkBadge={
                sinks.includes(n.id)
                  ? sinks.length === 1 ? "out" : "conflict"
                  : null
              }
              dropHints={dropHintsFor(n.id)}
              onHeaderMouseDown={(e) => onNodeHeaderMouseDown(n.id, e)}
              onPortMouseDown={(side, port, e) => onPortMouseDown(n.id, side, port, e)}
              onPortMouseUp={(side, port, e) => onPortMouseUp(n.id, side, port, e)}
              onDoubleClick={() => onNodeDoubleClick(n.id)}
            />
          );
        })}
      </div>
      <div className={styles.branchPanel}>
        <label className={styles.branchToggle}>
          <input
            type="checkbox"
            checked={showBranches}
            onChange={(e) => setShowBranches(e.target.checked)}
          />
          Ветки
        </label>
        {branches && (
          <div className={styles.branchLegend}>
            {branches.sink === null ? (
              // Молчать здесь нельзя: без финала подсветка не покажет
              // ничего, и это выглядело бы как «веток нет», а не как
              // «не от чего считать».
              <span className={styles.branchHint}>
                {sinks.length > 1
                  ? "финалов несколько — ветки не определены"
                  : "нет финального узла"}
              </span>
            ) : (
              <>
                <span style={{ color: BRANCH_COLORS.statement }}>■ условие</span>
                <span style={{ color: BRANCH_COLORS.answer }}>■ ответ</span>
                <span style={{ color: BRANCH_COLORS.both }}>■ общее</span>
                <span style={{ color: BRANCH_UNUSED }}>■ не в задании</span>
              </>
            )}
          </div>
        )}
      </div>
      <div className={styles.zoomLabel}>{Math.round(zoom * 100)}%</div>
    </div>
  );
}
