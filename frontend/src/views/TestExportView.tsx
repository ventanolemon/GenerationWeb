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
 * Тест: пользователь указывает количество вариантов, нажимает
 * «Сгенерировать», получает N разных StaticTask. Каждый — отдельная
 * вкладка. Экспорт — все варианты в один docx (FastAPI делает это
 * через цикл по count в /export).
 */
export default function TestExportView({ partition }: Props) {
  const [count, setCount] = useState(4);
  const [variants, setVariants] = useState<StaticTaskResponse[]>([]);
  const [activeTab, setActiveTab] = useState(0);
  const [showAnswers, setShowAnswers] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setLoading(true);
    setError(null);
    setVariants([]);
    try {
      // Параллельные запросы за вариантами. FastAPI обрабатывает каждый
      // вариант независимо, последовательная генерация была бы дольше.
      // Promise.allSettled чтобы один сбой не уронил всё.
      const settled = await Promise.allSettled(
        Array.from({ length: count }, () => api.generate(partition.id)),
      );
      const success: StaticTaskResponse[] = [];
      const failures: string[] = [];
      for (const s of settled) {
        if (s.status === "fulfilled") {
          if (s.value.type === "static") {
            success.push(s.value);
          } else {
            failures.push("получен не-статичный вариант");
          }
        } else {
          failures.push(String(s.reason));
        }
      }
      setVariants(success);
      setActiveTab(0);
      if (failures.length > 0) {
        setError(`${failures.length} вариант(ов) не сгенерировались`);
      }
    } finally {
      setLoading(false);
    }
  }

  async function exportAll() {
    try {
      const blob = await api.export({
        partitionId: partition.id,
        count,
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
        <label>
          Вариантов:{" "}
          <input
            type="number"
            min={1}
            max={50}
            value={count}
            onChange={(e) =>
              setCount(Math.max(1, Math.min(50, Number(e.target.value) || 1)))
            }
            style={{ width: "5rem" }}
          />
        </label>
        <button onClick={generate} disabled={loading}>
          {loading ? "Генерация…" : "Сгенерировать варианты"}
        </button>
        <button onClick={exportAll} disabled={loading}>
          Экспорт в Word
        </button>
        <label>
          <input
            type="checkbox"
            checked={showAnswers}
            onChange={(e) => setShowAnswers(e.target.checked)}
          />{" "}
          С ответами
        </label>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {variants.length > 0 && (
        <>
          <div className={styles.tabBar}>
            {variants.map((_, i) => (
              <button
                key={i}
                className={
                  i === activeTab
                    ? `${styles.tab} ${styles.tabActive}`
                    : styles.tab
                }
                onClick={() => setActiveTab(i)}
              >
                Вариант {i + 1}
              </button>
            ))}
          </div>
          <div className={styles.tabContent}>
            <BlockList blocks={variants[activeTab].statement} />
            {showAnswers && (
              <>
                <hr />
                <h3>Ответы</h3>
                <BlockList blocks={variants[activeTab].answer} />
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
