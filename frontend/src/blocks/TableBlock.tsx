import type { TableBlock } from "../api/types";
import styles from "../styles/blocks.module.css";

export default function TableBlockView({ block }: { block: TableBlock }) {
  return (
    <table className={styles.table}>
      {block.header && (
        <thead>
          <tr>
            {block.header.map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
      )}
      <tbody>
        {block.rows.map((row, r) => (
          <tr key={r}>
            {row.map((cell, c) => (
              <td key={c}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
