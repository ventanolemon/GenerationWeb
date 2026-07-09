// Узел на холсте: data-driven из каталога + derivePorts (динамические порты).
// Никакого знания о конкретных типах узлов — только данные.

import type { Catalog, GraphNodeJson } from "./types";
import { catalogNode, derivePorts } from "./model";
import {
  BODY_PAD,
  HEADER_H,
  NODE_W,
  ROW_H,
  nodeHeight,
  portColor,
} from "./geometry";
import styles from "../styles/graph-editor.module.css";

interface Props {
  catalog: Catalog;
  node: GraphNodeJson;
  x: number;
  y: number;
  selected: boolean;
  /** null — не финал; "out" — бейдж «ВЫХОД»; "conflict" — «ВЫХОД?». */
  sinkBadge: "out" | "conflict" | null;
  /** Подсветка входов при протяжке провода: имя порта → green | amber. */
  dropHints: Record<string, "green" | "amber"> | null;
  onHeaderMouseDown: (e: React.MouseEvent) => void;
  onPortMouseDown: (side: "in" | "out", port: string, e: React.MouseEvent) => void;
  onPortMouseUp: (side: "in" | "out", port: string, e: React.MouseEvent) => void;
  onDoubleClick: () => void;
}

export default function NodeItem({
  catalog, node, x, y, selected, sinkBadge, dropHints,
  onHeaderMouseDown, onPortMouseDown, onPortMouseUp, onDoubleClick,
}: Props) {
  const cn = catalogNode(catalog, node.type);
  const { inputs, outputs } = derivePorts(catalog, node);
  const h = nodeHeight(inputs.length, outputs.length);
  const title = cn?.display_name || node.type;

  return (
    <div
      className={`${styles.node} ${selected ? styles.nodeSelected : ""}`}
      style={{ left: x, top: y, width: NODE_W, height: h }}
      onDoubleClick={onDoubleClick}
      data-node-id={node.id}
    >
      <div
        className={styles.nodeHeader}
        style={{ height: HEADER_H }}
        onMouseDown={onHeaderMouseDown}
        title={cn?.description || node.type}
      >
        <span className={styles.nodeTitle}>{title}</span>
        {sinkBadge && (
          <span
            className={
              sinkBadge === "out" ? styles.sinkBadge : styles.sinkBadgeConflict
            }
          >
            {sinkBadge === "out" ? "ВЫХОД" : "ВЫХОД?"}
          </span>
        )}
      </div>
      <div className={styles.nodeId}>{node.id}</div>

      {inputs.map((p, i) => {
        const hint = dropHints?.[p.name];
        return (
          <div
            key={`in-${p.name}`}
            className={styles.portRow}
            style={{ top: HEADER_H + BODY_PAD + i * ROW_H, height: ROW_H, left: 0 }}
          >
            <span
              className={`${styles.portDot} ${styles.portDotIn} ${
                hint === "green" ? styles.portHintGreen
                : hint === "amber" ? styles.portHintAmber : ""
              }`}
              style={{ background: portColor(p.type) }}
              title={`${p.name}: ${p.type}${p.required ? " (обязателен)" : ""}`}
              onMouseDown={(e) => onPortMouseDown("in", p.name, e)}
              onMouseUp={(e) => onPortMouseUp("in", p.name, e)}
            />
            <span className={styles.portLabel}>{p.name}</span>
          </div>
        );
      })}

      {outputs.map((p, i) => (
        <div
          key={`out-${p.name}`}
          className={`${styles.portRow} ${styles.portRowOut}`}
          style={{ top: HEADER_H + BODY_PAD + i * ROW_H, height: ROW_H, right: 0 }}
        >
          <span className={styles.portLabel}>{p.name}</span>
          <span
            className={`${styles.portDot} ${styles.portDotOut}`}
            style={{ background: portColor(p.type) }}
            title={`${p.name}: ${p.type}`}
            onMouseDown={(e) => onPortMouseDown("out", p.name, e)}
            onMouseUp={(e) => onPortMouseUp("out", p.name, e)}
          />
        </div>
      ))}
    </div>
  );
}
