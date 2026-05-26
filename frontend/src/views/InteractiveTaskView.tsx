import { useEffect, useRef, useState } from "react";
import type { Block, Partition } from "../api/types";
import { api, ApiError } from "../api/client";
import { BlockList } from "../blocks/BlockRenderer";
import styles from "../styles/views.module.css";

interface Props {
  partition: Partition;
  userId?: string | null;
}

interface SessionState {
  sessionId: string;
  prompt: Block[];
  history: Block[][];  // массив "feedback" с прошлых ходов
  score: { correct: number; total: number };
  finished: boolean;
  supportsTolerant: boolean;
}

/**
 * Интерактивная сессия (тренажёр).
 *
 * Lifecycle:
 *   1. На монтировании / по «Заново» — POST /api/generate, получаем
 *      session_id и начальный prompt.
 *   2. На каждый submit — POST /api/interactive/submit, добавляем
 *      результат в history, либо обновляем prompt, либо помечаем сессию
 *      завершённой.
 *
 * История ходов скроллится сама в конец при каждом новом feedback —
 * через ref и useEffect.
 */
export default function InteractiveTaskView({ partition, userId }: Props) {
  const [session, setSession] = useState<SessionState | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tolerant, setTolerant] = useState(false);
  const historyRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Стартуем при монтировании. partition.id в зависимостях — на случай,
  // если пользователь переключится с одного интерактивного раздела на
  // другой, тот же компонент перерисует session с нуля.
  useEffect(() => {
    void startSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partition.id]);

  // Автоскролл истории вниз
  useEffect(() => {
    const el = historyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [session?.history.length]);

  async function startSession() {
    setLoading(true);
    setError(null);
    setSession(null);
    setInput("");
    try {
      const result = await api.generate(partition.id, userId);
      if (result.type !== "interactive") {
        throw new Error(
          "Раздел не интерактивный, попал не в тот компонент",
        );
      }
      setSession({
        sessionId: result.session_id,
        prompt: result.prompt,
        history: [],
        score: { correct: 0, total: 0 },
        finished: result.is_finished,
        supportsTolerant: result.supports_tolerant ?? false,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function submit() {
    if (!session || session.finished || input.trim() === "") return;
    const userInput = input;
    setInput("");
    try {
      const result = await api.submit(session.sessionId, userInput, tolerant);
      setSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          history: [...prev.history, result.feedback],
          score: {
            correct: prev.score.correct + (result.correct ? 1 : 0),
            total: prev.score.total + 1,
          },
          prompt: result.next_prompt ?? [],
          finished: result.is_finished,
          supportsTolerant: prev.supportsTolerant,
        };
      });
      // Возвращаем фокус в инпут — для тренажёра удобнее, чем тыкать мышью.
      inputRef.current?.focus();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      // 404 = сессия истекла, мягко предлагаем начать заново
      if (e instanceof ApiError && e.status === 404) {
        setError("Сессия завершилась или истекла. Нажмите «Заново».");
      } else {
        setError(msg);
      }
    }
  }

  return (
    <div className={styles.view}>
      <h2>{partition.name}</h2>
      {session && (
        <div className={styles.scoreLine}>
          Счёт: {session.score.correct} / {session.score.total}
          {"  "}
          <button onClick={startSession} className={styles.smallBtn}>
            Заново
          </button>
          {session.supportsTolerant && (
            <label className={styles.tolerantLabel}>
              <input
                type="checkbox"
                checked={tolerant}
                onChange={(e) => setTolerant(e.target.checked)}
              />
              {" "}Толерантная проверка (опечатки)
            </label>
          )}
        </div>
      )}

      {error && <div className={styles.error}>{error}</div>}

      {session && (
        <>
          <div className={styles.history} ref={historyRef}>
            {session.history.map((feedback, i) => (
              <div key={i} className={styles.historyItem}>
                <BlockList blocks={feedback} />
              </div>
            ))}
          </div>

          {!session.finished ? (
            <>
              <div className={styles.prompt}>
                <BlockList blocks={session.prompt} />
              </div>
              <form
                className={styles.inputRow}
                onSubmit={(e) => {
                  e.preventDefault();
                  void submit();
                }}
              >
                <input
                  ref={inputRef}
                  className={styles.answerInput}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Ваш ответ"
                  autoFocus
                />
                <button type="submit" disabled={loading || input.trim() === ""}>
                  Ответить
                </button>
              </form>
            </>
          ) : (
            <div className={styles.finishedBanner}>
              Сессия завершена. Нажмите «Заново», чтобы начать новую.
            </div>
          )}
        </>
      )}
    </div>
  );
}
