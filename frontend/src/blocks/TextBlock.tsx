import type { TextBlock } from "../api/types";
import styles from "../styles/blocks.module.css";

export default function TextBlockView({ block }: { block: TextBlock }) {
  // whiteSpace: pre-line через CSS — сохраняет переносы строк из ядра
  // (важно для матана, который возвращает многострочный условие).
  return <p className={styles.text}>{block.content}</p>;
}
