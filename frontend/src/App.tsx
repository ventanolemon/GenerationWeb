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
import LandingPage from "./views/LandingPage";
import ThemeToggle from "./components/ThemeToggle";
import ProfileModal from "./components/ProfileModal";
import AuthModal from "./components/AuthModal";
import { initials, avatarBackground } from "./utils/user";
import styles from "./styles/app.module.css";
import sidebarStyles from "./styles/sidebar.module.css";

const USER_STORAGE_KEY = "generator_user";
const GUEST_ID_KEY = "generator_guest_id";

function getOrCreateGuestId(): string {
  let id = localStorage.getItem(GUEST_ID_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(GUEST_ID_KEY, id);
  }
  return id;
}

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
 *  1. Авторизация — LandingPage показывается при первом запуске;
 *     user_info хранится в localStorage.
 *  2. PartitionControls — кнопки «+ Создать», «Изменить», «Удалить»
 *     под списком разделов.
 */
export default function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [guestId] = useState<string>(getOrCreateGuestId);

  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [partitions, setPartitions] = useState<Partition[]>([]);
  const [partition, setPartition] = useState<Partition | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [partitionsVersion, setPartitionsVersion] = useState(0);
  const [profileOpen, setProfileOpen] = useState(false);
  const [authModalOpen, setAuthModalOpen] = useState(false);

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

  // Профиль обновлён в окне профиля — синхронизируем состояние и localStorage.
  function handleUserUpdated(updated: UserInfo) {
    setUser(updated);
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(updated));
  }

  // Гость из окна профиля захотел зарегистрироваться.
  function handleRequestRegister() {
    setProfileOpen(false);
    setAuthModalOpen(true);
  }

  if (!authChecked) return null;

  if (!authenticated) {
    return <LandingPage onLogin={handleLogin} />;
  }

  const displayName = user ? user.fio || user.login : "Гость";

  return (
    <div className={styles.app}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>Γ</span>
          <h1 className={styles.title}>Генератор заданий</h1>
        </div>

        {/* Имя пользователя / гостевой режим — клик открывает профиль */}
        <div
          className={`${sidebarStyles.userBadge} ${sidebarStyles.userBadgeClickable}`}
          onClick={() => setProfileOpen(true)}
          title="Открыть профиль"
        >
          <span
            className={sidebarStyles.avatar}
            style={{ background: avatarBackground(user?.avatar_color) }}
          >
            {user ? initials(displayName) : "Г"}
          </span>
          <div className={sidebarStyles.userMeta}>
            <span className={sidebarStyles.userName}>{displayName}</span>
            <span className={sidebarStyles.userRole}>
              {user ? user.group || "Пользователь" : "Гостевой режим"}
            </span>
          </div>
          <button
            className={sidebarStyles.logoutBtn}
            onClick={(e) => { e.stopPropagation(); handleLogout(); }}
          >
            {user ? "Выйти" : "Войти"}
          </button>
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

        <div className={styles.sidebarSpacer} />
        <div className={styles.sidebarFooter}>
          <ThemeToggle />
        </div>
      </aside>
      <main className={styles.main}>
        {loadError && <div className={styles.error}>{loadError}</div>}
        {partition ? (
          <View key={partition.id} partition={partition} userId={user?.login ?? guestId} />
        ) : (
          <div className={styles.hint}>
            Выберите раздел слева, чтобы начать.
          </div>
        )}
      </main>

      {profileOpen && (
        <ProfileModal
          user={user}
          userId={user?.login ?? guestId}
          onClose={() => setProfileOpen(false)}
          onUserUpdated={handleUserUpdated}
          onRequestRegister={handleRequestRegister}
        />
      )}

      {authModalOpen && (
        <AuthModal
          initialTab="register"
          onLogin={(u) => { setAuthModalOpen(false); handleLogin(u); }}
          onClose={() => setAuthModalOpen(false)}
        />
      )}
    </div>
  );
}

function View({ partition, userId }: { partition: Partition; userId: string }) {
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
