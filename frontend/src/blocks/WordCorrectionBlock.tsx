import type { WordCorrectionBlock, DiffOp } from "../api/types";
import styles from "../styles/blocks.module.css";

/**
 * Обратная связь после ответа в тренажёре слов.
 * Структура из трёх строк:
 *   1) маркер (✓ / ≈ / ✗) + русский перевод
 *   2) что ввёл пользователь, с подсветкой ошибок через diff
 *   3) правильное написание (только при ошибке или мягком принятии)
 *
 * diff приходит из ядра уже структурированным массивом операций —
 * мы не парсим HTML, не делаем dangerouslySetInnerHTML, не доверяем
 * сервер на наличие нежелательного контента. Это и безопаснее, и
 * именно та архитектурная развязка, ради которой я отказался от
 * сырого HTML в core/dynamic_blocks.py на шаге 1.
 */
export default function WordCorrectionBlockView({ block }: { block: WordCorrectionBlock }) {
  const marker =
    block.correct && block.tolerant_accept ? "≈" :
    block.correct ? "✓" : "✗";
  const markerClass =
    block.correct && block.tolerant_accept ? styles.markerTolerant :
    block.correct ? styles.markerOk : styles.markerBad;

  const showCorrectAnswer = !block.correct || block.tolerant_accept;
  // Строго правильный ответ — рендерим целиком зелёным.
  // Иначе — поэлементный diff.
  const showDiff = !(block.correct && !block.tolerant_accept);

  return (
    <div className={styles.wordCorrection}>
      <div className={styles.wordHeader}>
        <span className={markerClass}>{marker}</span>{" "}
        <span className={styles.translation}>{block.translation}</span>
      </div>
      <div className={styles.wordRow}>
        <span className={styles.wordLabel}>ввод:</span>{" "}
        {showDiff ? (
          <DiffRender diff={block.diff} />
        ) : (
          <span className={styles.userAnswerOk}>{block.user_answer}</span>
        )}
      </div>
      {showCorrectAnswer && (
        <div className={styles.wordRow}>
          <span className={styles.wordLabel}>ответ:</span>{" "}
          <span className={styles.expected}>{block.expected}</span>
        </div>
      )}
    </div>
  );
}

function DiffRender({ diff }: { diff: DiffOp[] }) {
  // Каждая операция рендерится по-своему. Ничего опасного нет —
  // используем обычный JSX (text-content auto-escape).
  return (
    <span className={styles.diffSpan}>
      {diff.map((op, i) => (
        <DiffOpRender op={op} key={i} />
      ))}
    </span>
  );
}

function DiffOpRender({ op }: { op: DiffOp }) {
  switch (op.op) {
    case "equal":
      return <span className={styles.diffEqual}>{op.user}</span>;
    case "replace":
      // Пользователь написал что-то не то — показываем оба варианта
      return (
        <>
          <span className={styles.diffWrong}>{op.user}</span>
          <span className={styles.diffMissing}>[{op.expected}]</span>
        </>
      );
    case "delete":
      // Лишние буквы пользователя
      return <span className={styles.diffWrong}>{op.user}</span>;
    case "insert":
      // Пропущенные буквы
      return <span className={styles.diffMissing}>[{op.expected}]</span>;
  }
}
