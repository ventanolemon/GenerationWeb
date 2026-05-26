import { useState } from "react";
import type { Partition, StaticTaskResponse } from "../api/types";
import { api, ApiError } from "../api/client";
import { BlockList } from "../blocks/BlockRenderer";
import { triggerDownload } from "./StaticTaskView";
import styles from "../styles/views.module.css";

interface Props {
  partition: Partition;
}

/**
 * Накапливаемая таблица заданий. Каждый клик «Сгенерировать» добавляет
 * строку, кнопка ×  удаляет. Чекбокс «Показывать ответы» переключает,
 * показывать ли колонку с ответом.
 *
 * Используется для двух типов разделов:
 *   - физический конструктор (constracted=1)
 *   - группа (constracted=2), где у нас разные дочерние генераторы
 *     в каждой строке
 */
export default function TableTaskView({ partition }: Props) {
  const [tasks, setTasks] = useState<StaticTaskResponse[]>([]);
  const [showAnswers, setShowAnswers] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function addOne() {
    setLoading(true);
    setError(null);
    try {
      const result = await api.generate(partition.id);
      if (result.type !== "static") {
        throw new Error("Раздел вернул не статичное задание");
      }
      setTasks((prev) => [...prev, result]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function removeAt(index: number) {
    setTasks((prev) => prev.filter((_, i) => i !== index));
  }

  async function exportAll() {
    if (tasks.length === 0) return;
    try {
      const blob = await api.export({
        partitionId: partition.id,
        count: tasks.length,
        withAnswers: showAnswers,
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
        <button onClick={addOne} disabled={loading}>
          {loading ? "Генерация…" : "Сгенерировать"}
        </button>
        <button onClick={exportAll} disabled={tasks.length === 0}>
          Экспорт в Word ({tasks.length})
        </button>
        <label>
          <input
            type="checkbox"
            checked={showAnswers}
            onChange={(e) => setShowAnswers(e.target.checked)}
          />{" "}
          Показывать ответы
        </label>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {tasks.length > 0 && (
        <table className={styles.tableView}>
          <thead>
            <tr>
              <th className={styles.numCol}>№</th>
              <th>Условие</th>
              {showAnswers && <th>Ответ</th>}
              <th className={styles.actionsCol}></th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task, i) => (
              <tr key={i}>
                <td>{i + 1}</td>
                <td>
                  <BlockList blocks={task.statement} />
                </td>
                {showAnswers && (
                  <td>
                    <BlockList blocks={task.answer} />
                  </td>
                )}
                <td>
                  <button
                    className={styles.deleteBtn}
                    onClick={() => removeAt(i)}
                    aria-label="Удалить"
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
