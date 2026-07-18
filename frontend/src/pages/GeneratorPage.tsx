import { useEffect, useState } from "react";
import type { Partition, Subject } from "../api/types";
import { api } from "../api/client";
import { useSession } from "../session";
import SubjectPicker from "../components/SubjectPicker";
import PartitionList from "../components/PartitionList";
import PartitionControls from "../components/PartitionControls";
import StaticTaskView from "../views/StaticTaskView";
import TableTaskView from "../views/TableTaskView";
import TestExportView from "../views/TestExportView";
import InteractiveTaskView from "../views/InteractiveTaskView";
import ScrollToTop from "../components/ScrollToTop";
import { APP_NAME, APP_VERSION } from "../meta";
import styles from "../styles/app.module.css";

/**
 * Маршрут «/» — генератор заданий. Вынесен из App при вводе роутера:
 * бренд/пользователь/тема переехали в глобальную панель (AppLayout), здесь
 * остались предметно-раздельная навигация (сайдбар) и область задания.
 */
export default function GeneratorPage() {
  const { effectiveUserId } = useSession();

  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [partitions, setPartitions] = useState<Partition[]>([]);
  const [partition, setPartition] = useState<Partition | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [partitionsVersion, setPartitionsVersion] = useState(0);
  const [mainEl, setMainEl] = useState<HTMLElement | null>(null);

  useEffect(() => {
    api
      .listSubjects()
      .then((data) => {
        setSubjects(data);
        if (data.length > 0) setSubjectId(data[0].id);
      })
      .catch((e) => setLoadError(String(e)));
  }, []);

  useEffect(() => {
    if (subjectId === null) return;
    setPartitions([]);
    setPartition(null);
    api
      .listPartitions(subjectId)
      .then(setPartitions)
      .catch((e) => setLoadError(String(e)));
  }, [subjectId, partitionsVersion]);

  function handlePartitionsChanged() {
    setPartition(null);
    setPartitionsVersion((v) => v + 1);
  }

  return (
    <div className={styles.app}>
      <aside className={styles.sidebar}>
        <SubjectPicker
          subjects={subjects}
          selectedId={subjectId}
          onSelect={setSubjectId}
        />
        <PartitionList
          partitions={partitions}
          selectedId={partition?.id ?? null}
          onSelect={setPartition}
        />
        <PartitionControls
          subjectId={subjectId}
          selected={partition}
          onChanged={handlePartitionsChanged}
        />

        <div className={styles.sidebarSpacer} />
        <div className={styles.sidebarFooter}>
          <div className={styles.sidebarMeta}>
            <span className={styles.sidebarAppName}>{APP_NAME}</span>
            <span className={styles.sidebarVersion}>v{APP_VERSION}</span>
          </div>
        </div>
      </aside>

      <main className={styles.main} ref={setMainEl}>
        {loadError && <div className={styles.error}>{loadError}</div>}
        {partition ? (
          <TaskView key={partition.id} partition={partition} userId={effectiveUserId} />
        ) : (
          <div className={styles.hint}>Выберите раздел слева, чтобы начать.</div>
        )}
        <ScrollToTop target={mainEl} />
      </main>
    </div>
  );
}

function TaskView({ partition, userId }: { partition: Partition; userId: string }) {
  if (partition.is_interactive) {
    return <InteractiveTaskView partition={partition} userId={userId} />;
  }
  switch (partition.view_kind) {
    case "single":
      return <StaticTaskView partition={partition} />;
    case "table":
      return <TableTaskView partition={partition} />;
    case "test":
      return <TestExportView partition={partition} />;
    default:
      return <div>Неизвестный тип раздела: {partition.view_kind}</div>;
  }
}
