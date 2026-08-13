import { useState } from "react";
import type { Partition, StaticTaskResponse } from "../api/types";
import { api } from "../api/client";
import ExportDialog from "../components/ExportDialog";
import { BlockList } from "../blocks/BlockRenderer";
import AcceptedAnswers from "./AcceptedAnswers";
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
  const [exporting, setExporting] = useState(false);
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

  // Экспорт открывает диалог: одной галочки «с ответами» мало —
  // размещений четыре, и лист с ключом под каждым заданием
  // студентам не раздашь.

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
            <button onClick={() => setExporting(true)}>Экспорт в Word</button>
          </>
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {task && (
        <div className={styles.content}>
          <BlockList blocks={showingAnswer ? task.answer : task.statement} />
          {/* Предпросмотр «что примут» показываем только вместе с
              ответом. Список засчитываемых ответов — это ответ и есть,
              и рядом с условием ему не место. */}
          {showingAnswer && task.answer_spec && (
            <AcceptedAnswers spec={task.answer_spec} />
          )}
        </div>
      )}
          {exporting && (
        <ExportDialog
          partitionId={partition.id}
          partitionName={partition.name}
          defaultCount={1}
          onClose={() => setExporting(false)}
        />
      )}
    </div>
  );
}

/** Сохранить Blob как файл, инициировав скачивание. */
