import { useState } from "react";
import type { Partition, StaticTaskResponse } from "../api/types";
import { api, ApiError } from "../api/client";
import { BlockList } from "../blocks/BlockRenderer";
import styles from "../styles/views.module.css";

interface Props {
  partition: Partition;
}

/**
 * Одно задание, кнопки «Сгенерировать», «Показать ответ», «Экспорт».
 * Прямой аналог desktop StaticTaskView.
 */
export default function StaticTaskView({ partition }: Props) {
  const [task, setTask] = useState<StaticTaskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showingAnswer, setShowingAnswer] = useState(false);

  async function generate() {
    setLoading(true);
    setError(null);
    try {
      const result = await api.generate(partition.id);
      if (result.type !== "static") {
        // Раздел зарегистрирован как single, но генератор вернул что-то
        // другое. Это инцидент конфигурации, не ошибка пользователя.
        throw new Error(
          "Ожидалось статичное задание, получено: " + result.type,
        );
      }
      setTask(result);
      setShowingAnswer(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function exportOne() {
    if (!task) return;
    try {
      const blob = await api.export({
        partitionId: partition.id,
        count: 1,
        withAnswers: true,
      });
      triggerDownload(blob, `${partition.name}.docx`);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      setError(`Не удалось экспортировать: ${msg}`);
    }
  }

  return (
    <div className={styles.view}>
      <h2>{partition.name}</h2>
      <div className={styles.controls}>
        <button onClick={generate} disabled={loading}>
          {loading ? "Генерация…" : "Сгенерировать"}
        </button>
        {task && (
          <>
            <button onClick={() => setShowingAnswer((s) => !s)}>
              {showingAnswer ? "Показать условие" : "Показать ответ"}
            </button>
            <button onClick={exportOne}>Экспорт в Word</button>
          </>
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {task && (
        <div className={styles.content}>
          <BlockList blocks={showingAnswer ? task.answer : task.statement} />
        </div>
      )}
    </div>
  );
}

/** Сохранить Blob как файл, инициировав скачивание. */
export function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Освобождаем blob URL — браузер иначе будет держать его до перезагрузки.
  URL.revokeObjectURL(url);
}
