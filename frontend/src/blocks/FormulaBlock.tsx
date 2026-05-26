import type { FormulaBlock } from "../api/types";
import styles from "../styles/blocks.module.css";

/**
 * Формула. PNG приходит base64-кодированным из ядра (matplotlib mathtext).
 * Если ядру не удалось отрендерить — image_b64 === null, и мы показываем
 * сырой LaTeX в обёртке $...$, чтобы хотя бы видна была математика.
 *
 * Альт-текст содержит LaTeX-исходник: это и для accessibility (screen
 * readers), и для копирования формулы в буфер обмена.
 */
export default function FormulaBlockView({ block }: { block: FormulaBlock }) {
  if (block.image_b64) {
    return (
      <img
        className={styles.formula}
        src={`data:image/png;base64,${block.image_b64}`}
        alt={block.latex}
      />
    );
  }
  return (
    <code className={styles.formulaFallback}>
      ${block.latex}$
    </code>
  );
}
