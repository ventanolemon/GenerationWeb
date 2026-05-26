import { useEffect, useState } from "react";
import type { Partition, Subject, UserInfo } from "./api/types";
import { api } from "./api/client";
import SubjectPicker from "./components/SubjectPicker";
import PartitionList from "./components/PartitionList";
import PartitionControls from "./components/PartitionControls";
import StaticTaskView from "./views/StaticTaskView";
import TableTaskView from "./views/TableTaskView";
import TestExportView from "./views/TestExportView";
import InteractiveTaskView from "./views/InteractiveTaskView";
import LoginPage from "./views/LoginPage";
import styles from "./styles/app.module.css";
import sidebarStyles from "./styles/sidebar.module.css";

const USER_STORAGE_KEY = "generator_user";

function loadStoredUser(): UserInfo | null {
  try {
    const raw = localStorage.getItem(USER_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as UserInfo) : null;
  } catch {
    return null;
  }
}

/**
 * Корневой компонент.
 *
 * Добавлено по сравнению с первоначальной версией:
 *  1. Авторизация — LoginPage показывается при первом запуске;
 *     user_info хранится в localStorage.
 *  2. PartitionControls — кнопки «+ Создать», «Изменить», «Удалить»
 *     под списком разделов.
 */
export default function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [partitions, setPartitions] = useState<Partition[]>([]);
  const [partition, setPartition] = useState<Partition | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [partitionsVersion, setPartitionsVersion] = useState(0);

  // Проверяем сохранённую сессию при старте
  useEffect(() => {
    const stored = loadStoredUser();
    if (stored !== null || localStorage.getItem(USER_STORAGE_KEY) === "guest") {
      setUser(stored);
      setAuthenticated(true);
    }
    setAuthChecked(true);
  }, []);

  // Загрузить предметы после аутентификации
  useEffect(() => {
    if (!authenticated) return;
    api
      .listSubjects()
      .then((data) => {
        setSubjects(data);
        if (data.length > 0) setSubjectId(data[0].id);
      })
      .catch((e) => setLoadError(String(e)));
  }, [authenticated]);

  // Перезагружать разделы при смене предмета или после мутации (partitionsVersion)
  useEffect(() => {
    if (subjectId === null) return;
    setPartitions([]);
    setPartition(null);
    api
      .listPartitions(subjectId)
      .then(setPartitions)
      .catch((e) => setLoadError(String(e)));
  }, [subjectId, partitionsVersion]);

  function handleLogin(userInfo: UserInfo | null) {
    setUser(userInfo);
    setAuthenticated(true);
    if (userInfo) {
      localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(userInfo));
    } else {
      localStorage.setItem(USER_STORAGE_KEY, "guest");
    }
  }

  function handleLogout() {
    setAuthenticated(false);
    setUser(null);
    localStorage.removeItem(USER_STORAGE_KEY);
    setSubjects([]);
    setSubjectId(null);
    setPartitions([]);
    setPartition(null);
  }

  function handlePartitionsChanged() {
    setPartition(null);
    setPartitionsVersion((v) => v + 1);
  }

  if (!authChecked) return null;

  if (!authenticated) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return (
    <div className={styles.app}>
      <aside className={styles.sidebar}>
        <h1 className={styles.title}>Генератор заданий</h1>

        {/* Имя пользователя / гостевой режим */}
        <div className={sidebarStyles.userBadge}>
          {user ? (
            <>
              <span>{user.fio || user.login}</span>
              <button className={sidebarStyles.logoutBtn} onClick={handleLogout}>
                Выйти
              </button>
            </>
          ) : (
            <>
              <span>Гость</span>
              <button className={sidebarStyles.logoutBtn} onClick={handleLogout}>
                Войти
              </button>
            </>
          )}
        </div>

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
      </aside>
      <main className={styles.main}>
        {loadError && <div className={styles.error}>{loadError}</div>}
        {partition ? (
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
