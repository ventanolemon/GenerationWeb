import type { CodeBlock } from "../api/types";
import styles from "../styles/blocks.module.css";

/**
 * Листинг кода с моноширинным шрифтом. Без подсветки синтаксиса —
 * она потребовала бы prismjs/highlight.js, ради задания «найти ошибки
 * в C-коде» это overkill. Подсветку можно добавить позже одним местом.
 *
 * data-language нужен для возможной кастомной стилизации по языку
 * (например, .codeBlock[data-language="c"] { border-left: orange })
 * и для отображения языка в углу через CSS.
 */
export default function CodeBlockView({ block }: { block: CodeBlock }) {
  return (
    <pre className={styles.codeBlock} data-language={block.language}>
      <code>{block.code}</code>
    </pre>
  );
}
