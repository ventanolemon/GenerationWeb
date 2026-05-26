import { useEffect, useState } from "react";
import type { Partition, Subject } from "./api/types";
import { api } from "./api/client";
import SubjectPicker from "./components/SubjectPicker";
import PartitionList from "./components/PartitionList";
import StaticTaskView from "./views/StaticTaskView";
import TableTaskView from "./views/TableTaskView";
import TestExportView from "./views/TestExportView";
import InteractiveTaskView from "./views/InteractiveTaskView";
import styles from "./styles/app.module.css";

/**
 * Корневой компонент. Управляет двумя состояниями: выбранный предмет
 * и выбранный раздел. Содержимое правой панели выбирается по двум
 * сигналам с бэка (view_kind из БД + наличие capabilities в генераторе).
 *
 * Выбор view-компонента — единственное место, где у нас вынужденный
 * switch по строке. Это аналог GeneratorWindow._pick_view из десктопа.
 * Альтернатива (полиморфная мапа view_kind → component) — overkill для
 * четырёх случаев.
 */
export default function App() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [partitions, setPartitions] = useState<Partition[]>([]);
  const [partition, setPartition] = useState<Partition | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Загрузить предметы при старте
  useEffect(() => {
    api
      .listSubjects()
      .then((data) => {
        setSubjects(data);
        if (data.length > 0) setSubjectId(data[0].id);
      })
      .catch((e) => setLoadError(String(e)));
  }, []);

  // Перезагружать разделы при смене предмета
  useEffect(() => {
    if (subjectId === null) return;
    setPartitions([]);
    setPartition(null);
    api
      .listPartitions(subjectId)
      .then(setPartitions)
      .catch((e) => setLoadError(String(e)));
  }, [subjectId]);

  return (
    <div className={styles.app}>
      <aside className={styles.sidebar}>
        <h1 className={styles.title}>Генератор заданий</h1>
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
      </aside>
      <main className={styles.main}>
        {loadError && <div className={styles.error}>{loadError}</div>}
        {partition ? (
          // key={partition.id} — заставляет React пересоздать поддерево при
          // смене раздела. Иначе состояние (накопленные задания, открытая
          // сессия) переедет в новый раздел, что мы не хотим.
          <View key={partition.id} partition={partition} />
        ) : (
          <div className={styles.hint}>
            Выберите раздел слева, чтобы начать.
          </div>
        )}
      </main>
    </div>
  );
}

/** Подбор view-компонента по типу раздела.
 *
 * is_interactive имеет приоритет над view_kind — интерактивная сессия
 * не может рендериться как таблица или тест, у неё другой цикл
 * взаимодействия. Это совпадает с логикой десктопа (см. GeneratorWindow._pick_view).
 */
function View({ partition }: { partition: Partition }) {
  if (partition.is_interactive) {
    return <InteractiveTaskView partition={partition} />;
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
