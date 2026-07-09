// Предпросмотр графа: POST /graph/preview на нескольких seed, блоки
// условия/ответа рендерятся СУЩЕСТВУЮЩИМ BlockRenderer (правило §2:
// превью на вебе бесплатно — ничего нового для рендера не пишем).

import type { Block } from "../api/types";
import type { PreviewResponse } from "./types";
import { BlockList } from "../blocks/BlockRenderer";
import styles from "../styles/graph-editor.module.css";

interface Props {
  preview: PreviewResponse | null;
  loading: boolean;
  onClose: () => void;
}

export default function PreviewPanel({ preview, loading, onClose }: Props) {
  return (
    <div className={styles.previewPanel}>
      <div className={styles.previewHeader}>
        <b>Предпросмотр</b>
        <button className={styles.previewClose} onClick={onClose}>×</button>
      </div>
      {loading && <div className={styles.previewStatus}>Исполняю граф…</div>}
      {!loading && preview && !preview.ok && (
        <div className={styles.previewError}>
          {preview.errors.join("\n") || "граф не собрался"}
        </div>
      )}
      {!loading &&
        preview?.runs.map((run) => (
          <div key={run.seed} className={styles.previewRun}>
            <div className={styles.previewSeed}>
              seed {run.seed} · {run.attempts} поп. · {run.wall_ms} мс
            </div>
            {run.error ? (
              <div className={styles.previewError}>{run.error}</div>
            ) : (
              <>
                <BlockList blocks={run.statement as Block[]} />
                <div className={styles.previewAnswerLabel}>Ответ</div>
                <BlockList blocks={run.answer as Block[]} />
              </>
            )}
          </div>
        ))}
    </div>
  );
}
