import { useState } from "react";
import type { AnswerPreview, AnswerSpec } from "../api/types";
import { api } from "../api/client";
import styles from "../styles/views.module.css";

interface Props {
  spec: AnswerSpec;
}

/**
 * «Что примут» — панель ПРЕПОДАВАТЕЛЯ.
 *
 * Зачем она вообще (план, §5): без списка засчитываемых ответов рядом с
 * переключателем строгости автопроверку выключают на второй день, потому
 * что ей не доверяют. Инвариант «предпросмотр не врёт» держится в ядре:
 * каждый пример прогоняется через собственный `check()`, и что не прошло —
 * не показывается.
 *
 * Почему по кнопке, а не сразу. Для выражения предпросмотр в мягком
 * режиме стоит около 200 мс — там на каждого кандидата работает
 * `simplify`. Считать это при каждом показе задания значило бы платить
 * впятеро за подсказку, которую смотрят один раз при настройке.
 *
 * Почему два режима рядом. Тумблер строгости меняет не «строже/мягче
 * вообще», а конкретный список принимаемых ответов, и увидеть разницу
 * ДО переключения важнее, чем прочитать про неё в документации.
 */
export default function AcceptedAnswers({ spec }: Props) {
  const [previews, setPreviews] = useState<Record<string, AnswerPreview>>({});
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(mode: "soft" | "strict") {
    setLoading(mode);
    setError(null);
    try {
      const preview = await api.previewAnswer(spec, mode);
      setPreviews((prev) => ({ ...prev, [mode]: preview }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(null);
    }
  }

  const current = (spec.mode ?? "soft") as "soft" | "strict";

  return (
    <div className={styles.acceptedPanel}>
      <div className={styles.acceptedHead}>
        <strong>Что примут</strong>
        <span className={styles.acceptedMode}>
          режим задания: {current === "strict" ? "строгий" : "мягкий"}
        </span>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {(["soft", "strict"] as const).map((mode) => {
        const preview = previews[mode];
        return (
          <div key={mode} className={styles.acceptedRow}>
            <button
              className={styles.smallBtn}
              onClick={() => void load(mode)}
              disabled={loading !== null}
            >
              {loading === mode
                ? "Считаю…"
                : mode === "soft"
                  ? "Мягкий режим"
                  : "Строгий режим"}
            </button>
            {preview && (
              <div className={styles.acceptedList}>
                {preview.examples.length === 0 ? (
                  // Пустой список — не сбой, а результат: так бывает,
                  // когда ответ не разбирается. Скрыть это значило бы
                  // оставить преподавателя с заданием, которое не примет
                  // ничего, и без единого признака, что это так.
                  <span className={styles.acceptedEmpty}>
                    Ни один пример не прошёл проверку — задание не примет
                    даже собственный ответ.
                  </span>
                ) : (
                  preview.examples.map((example) => (
                    <code key={example} className={styles.acceptedExample}>
                      {example}
                    </code>
                  ))
                )}
                {preview.tolerance && (
                  <span className={styles.acceptedHint}>
                    допуск: {preview.tolerance}
                  </span>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
