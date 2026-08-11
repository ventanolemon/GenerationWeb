import type { TextBlock } from "../api/types";
import styles from "../styles/blocks.module.css";

/** Кегль задаётся классом, а не пунктами: у экрана своя типографика. */
const SIZE_CLASS = {
  small: styles.textSmall,
  normal: undefined,
  large: styles.textLarge,
} as const;

export default function TextBlockView({ block }: { block: TextBlock }) {
  // whiteSpace: pre-line через CSS — сохраняет переносы строк из ядра
  // (важно для матана, который возвращает многострочный условие).
  const className = [styles.text, SIZE_CLASS[block.size ?? "normal"]]
    .filter(Boolean)
    .join(" ");
  return (
    <p
      className={className}
      style={{
        fontWeight: block.bold ? 600 : undefined,
        fontStyle: block.italic ? "italic" : undefined,
      }}
    >
      {block.content}
    </p>
  );
}
