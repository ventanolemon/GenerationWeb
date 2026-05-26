import { useState } from "react";
import type { FillInBlankBlock } from "../api/types";
import styles from "../styles/blocks.module.css";

/**
 * Шаблон с пропусками. Каждый "___" в template заменяется на <input>.
 * Подсветка по мере набора:
 *   - пустое поле — нейтральный фон,
 *   - правильно   — зелёный,
 *   - неправильно — красный.
 *
 * Это та же логика, что в Qt-версии (см. core/dynamic_blocks.py),
 * только перенесённая на React с локальным state.
 *
 * Состояние ответов локально — нам не нужно его поднимать наверх,
 * потому что блок самодостаточный: пользователь видит правильность
 * ответа сразу, без отдельной кнопки «Проверить».
 */
export default function FillInBlankBlockView({ block }: { block: FillInBlankBlock }) {
  const [values, setValues] = useState<string[]>(() =>
    block.answers.map(() => ""),
  );

  // template состоит из текстовых сегментов, разделённых placeholder'ами.
  // Их количество всегда на 1 больше количества answers (split всегда
  // даёт N+1 частей при N разделителях).
  const segments = block.template.split(block.placeholder);

  function checkValue(value: string, expected: string): boolean | null {
    if (value === "") return null; // пустое — пока не оцениваем
    const a = block.case_sensitive ? value.trim() : value.trim().toLowerCase();
    const b = block.case_sensitive ? expected.trim() : expected.trim().toLowerCase();
    return a === b;
  }

  function setAt(index: number, v: string) {
    setValues((prev) => prev.map((x, i) => (i === index ? v : x)));
  }

  return (
    <div className={styles.fillInBlank}>
      {segments.map((segment, i) => (
        <span key={i} className={styles.fillInSegment}>
          {segment}
          {i < block.answers.length && (
            <Input
              value={values[i]}
              status={checkValue(values[i], block.answers[i])}
              onChange={(v) => setAt(i, v)}
            />
          )}
        </span>
      ))}
    </div>
  );
}

function Input({
  value,
  status,
  onChange,
}: {
  value: string;
  status: boolean | null;
  onChange: (v: string) => void;
}) {
  const cls =
    status === null
      ? styles.blankInput
      : status
      ? `${styles.blankInput} ${styles.blankInputOk}`
      : `${styles.blankInput} ${styles.blankInputBad}`;
  return (
    <input
      className={cls}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="..."
      // size="8" ужимает <input> до ширины ~8 символов, что выглядит
      // ближе к настоящим пропускам в учебнике, чем full-width поле.
      size={Math.max(8, value.length + 2)}
    />
  );
}
