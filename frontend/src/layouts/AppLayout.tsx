import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useSession } from "../session";
import type { Role } from "../api/types";
import { initials, avatarBackground } from "../utils/user";
import ThemeToggle from "../components/ThemeToggle";
import ProfileModal from "../components/ProfileModal";
import AuthModal from "../components/AuthModal";
import styles from "../styles/appshell.module.css";

const ROLE_RU: Record<Role, string> = {
  student: "студент",
  teacher: "преподаватель",
  admin: "администратор",
};

interface Tab {
  to: string;
  label: string;
  end?: boolean;
  /** Виден ли пункт при данной роли и статусе входа (гость → user===null). */
  visible(role: Role, isGuest: boolean): boolean;
}

// Навигация по разделам. Гейтинг — только UX: сервер всё равно авторитетен
// (401 без identity, 403 при недостатке роли). Гость видит лишь генератор.
const TABS: Tab[] = [
  { to: "/", label: "Генератор", end: true, visible: () => true },
  {
    to: "/analytics",
    label: "Аналитика",
    visible: (role) => role === "teacher" || role === "admin",
  },
  {
    to: "/contour",
    label: "Контур",
    visible: (role) => role === "teacher" || role === "admin",
  },
  { to: "/admin", label: "Администрирование", visible: (role) => role === "admin" },
  { to: "/homework", label: "Домашки", visible: (_role, isGuest) => !isGuest },
];

/**
 * Оболочка всех маршрутов: верхняя панель (бренд + навигация + тема +
 * профиль) и <Outlet/> для контента. Модалки профиля/регистрации живут
 * здесь, потому что триггер (плашка пользователя) — часть панели.
 */
export default function AppLayout() {
  const session = useSession();
  const { user, role, effectiveUserId } = session;
  const isGuest = user === null;

  const [profileOpen, setProfileOpen] = useState(false);
  // null — закрыта; иначе вкладка, с которой открыть (регистрация из
  // профиля гостя vs. вход по кнопке «Войти» в плашке пользователя).
  const [authTab, setAuthTab] = useState<"login" | "register" | null>(null);

  const displayName = user ? user.fio || user.login : "Гость";
  const roleLabel = isGuest ? "гостевой режим" : ROLE_RU[role];

  const tabs = TABS.filter((t) => t.visible(role, isGuest));

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <NavLink to="/" className={styles.brand} end>
          <span className={styles.brandMark}>Λ+</span>
          <span className={styles.brandText}>
            <span className={styles.brandName}>Лаборатория+</span>
            <span className={styles.brandSub}>Генератор заданий</span>
          </span>
        </NavLink>

        <nav className={styles.tabs} aria-label="Разделы">
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                isActive ? `${styles.tab} ${styles.tabActive}` : styles.tab
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>

        <span className={styles.spacer} />
        <ThemeToggle />

        <div
          className={styles.whoami}
          onClick={() => setProfileOpen(true)}
          title="Открыть профиль"
        >
          <span
            className={styles.avatar}
            style={{ background: avatarBackground(user?.avatar_color) }}
          >
            {user ? initials(displayName) : "Г"}
          </span>
          <span>
            <span className={styles.whoName}>{displayName}</span>
            <span className={styles.whoRole}>
              {isGuest ? roleLabel : `${user!.login} · ${roleLabel}`}
            </span>
          </span>
          <button
            type="button"
            className={styles.logoutBtn}
            title={isGuest ? "Войти в аккаунт" : "Выйти из аккаунта"}
            onClick={(e) => {
              // Не всплывать до onClick плашки — иначе вместо выхода
              // откроется профиль.
              e.stopPropagation();
              if (isGuest) {
                setAuthTab("login");
                return;
              }
              if (window.confirm("Выйти из аккаунта?")) {
                session.logout();
              }
            }}
          >
            {isGuest ? "Войти" : "Выйти"}
          </button>
        </div>
      </header>

      <main className={styles.main}>
        <Outlet />
      </main>

      {profileOpen && (
        <ProfileModal
          user={user}
          userId={effectiveUserId}
          onClose={() => setProfileOpen(false)}
          onUserUpdated={session.updateUser}
          onRequestRegister={() => {
            setProfileOpen(false);
            setAuthTab("register");
          }}
        />
      )}

      {authTab && (
        <AuthModal
          initialTab={authTab}
          onLogin={(u) => {
            setAuthTab(null);
            if (u) session.updateUser(u);
          }}
          onClose={() => setAuthTab(null)}
        />
      )}
    </div>
  );
}
