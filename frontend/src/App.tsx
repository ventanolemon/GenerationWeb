import { useEffect, useMemo, useState } from "react";
import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import type { Role, UserInfo } from "./api/types";
import { api } from "./api/client";
import {
  SessionProvider, effectiveRole, readActingRole, useSession, writeActingRole,
} from "./session";
import type { SessionValue } from "./session";
import LandingPage from "./views/LandingPage";
import AppLayout from "./layouts/AppLayout";
import GeneratorPage from "./pages/GeneratorPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import SubjectsPage from "./pages/SubjectsPage";
import AdminPage from "./pages/AdminPage";
import HomeworkPage from "./pages/HomeworkPage";
import ContourPage from "./pages/ContourPage";
import CorpusPage from "./pages/CorpusPage";

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
    return raw && raw !== "guest" ? (JSON.parse(raw) as UserInfo) : null;
  } catch {
    return null;
  }
}

/**
 * Корень приложения. Отвечает за аутентификацию и сборку сессии; всё
 * остальное — за роутером (AppLayout + страницы). Гейтинг маршрутов —
 * RequireRole / RequireUser (UX; сервер авторитетен через X-User-Role).
 */
export default function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [guestId] = useState<string>(getOrCreateGuestId);
  // Примерка роли (режим разработчика). Начальное значение читается из
  // sessionStorage: перезагрузка посреди отладки не должна молча вернуть
  // разработчика к собственной картине.
  const [actingRole, setActingRole] = useState<Role | null>(readActingRole);
  const [canTryOn, setCanTryOn] = useState(false);

  useEffect(() => {
    const stored = loadStoredUser();
    if (stored !== null || localStorage.getItem(USER_STORAGE_KEY) === "guest") {
      setUser(stored);
      setAuthenticated(true);
    }
    setAuthChecked(true);
  }, []);

  // Право примерять роль спрашиваем у СЕРВЕРА, один раз на вход. Не из
  // сохранённого профиля: флаг разработчика в нём не лежит, а угадывать
  // его по роли неверно — «админ организации» и «администратор
  // развёртывания» это разные оси (§8.2).
  useEffect(() => {
    if (!user?.token) {
      setCanTryOn(false);
      return;
    }
    let alive = true;
    api.me({ login: user.login, role: user.role, token: user.token })
      .then((who) => { if (alive) setCanTryOn(who.can_try_on); })
      .catch(() => { if (alive) setCanTryOn(false); });
    return () => { alive = false; };
  }, [user?.login, user?.token, user?.role]);

  function handleLogin(userInfo: UserInfo | null) {
    setUser(userInfo);
    setAuthenticated(true);
    localStorage.setItem(
      USER_STORAGE_KEY,
      userInfo ? JSON.stringify(userInfo) : "guest",
    );
  }

  function handleLogout() {
    if (user?.token) {
      void api.logout({ login: user.login, role: user.role, token: user.token });
    }
    setAuthenticated(false);
    setUser(null);
    localStorage.removeItem(USER_STORAGE_KEY);
    // Выход снимает примерку: иначе следующий вошедший в этой же вкладке
    // получит чужой режим отладки и не поймёт, почему интерфейс урезан.
    writeActingRole(null);
    setActingRole(null);
  }

  function updateUser(updated: UserInfo) {
    // Токен сохраняем: он приходит ТОЛЬКО с ответа на вход, а профиль
    // (GET/PATCH /profile) его не несёт. Затирать им сохранённый — значит
    // молча разлогинить человека на сервере после правки своего же имени:
    // локально он остаётся «вошедшим», а запросы начинают получать 401.
    const merged = { ...updated, token: updated.token ?? user?.token };
    setUser(merged);
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(merged));
  }

  const session = useMemo<SessionValue | null>(() => {
    if (!authenticated) return null;
    const trueRole = effectiveRole(user);
    // Примерка подменяет роль ЦЕЛИКОМ, а не добавляется рядом: витрины
    // гейтятся по `role`, и оставь мы здесь настоящую — интерфейс менялся
    // бы только там, где о примерке отдельно вспомнили.
    const role: Role = actingRole ?? trueRole;
    return {
      user,
      guestId,
      role,
      identity: user
        ? {
            login: user.login, role, token: user.token,
            actingRole: actingRole ?? undefined,
          }
        : null,
      effectiveUserId: user?.login ?? guestId,
      logout: handleLogout,
      updateUser,
      // Регистрация из профиля обрабатывается в AppLayout (открывает
      // AuthModal); поле требуется контрактом сессии — здесь no-op.
      requestRegister: () => {},
      canTryOn,
      actingRole,
      trueRole: actingRole ? trueRole : null,
      tryOnRole: (next: Role | null) => {
        writeActingRole(next);
        setActingRole(next);
      },
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticated, user, guestId, actingRole, canTryOn]);

  if (!authChecked) return null;

  if (!authenticated || session === null) {
    return <LandingPage onLogin={handleLogin} />;
  }

  return (
    <SessionProvider value={session}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<GeneratorPage />} />
          <Route
            path="analytics"
            element={
              <RequireRole roles={["teacher", "admin"]}>
                <AnalyticsPage />
              </RequireRole>
            }
          />
          <Route
            path="contour"
            element={
              <RequireRole roles={["teacher", "admin"]}>
                <ContourPage />
              </RequireRole>
            }
          />
          <Route
            path="subjects"
            element={
              <RequireRole roles={["teacher", "admin"]}>
                <SubjectsPage />
              </RequireRole>
            }
          />
          <Route
            path="admin"
            element={
              <RequireRole roles={["admin"]}>
                <AdminPage />
              </RequireRole>
            }
          />
          <Route
            path="corpus"
            element={
              <RequireRole roles={["admin"]}>
                <CorpusPage />
              </RequireRole>
            }
          />
          <Route
            path="homework"
            element={
              <RequireUser>
                <HomeworkPage />
              </RequireUser>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </SessionProvider>
  );
}

/** Пускает на маршрут только при подходящей роли, иначе — на генератор. */
function RequireRole({
  roles,
  children,
}: {
  roles: Role[];
  children: ReactElement;
}) {
  const { role } = useSession();
  return roles.includes(role) ? children : <Navigate to="/" replace />;
}

/** Пускает только вошедшего (не гостя) — домашки требуют identity. */
function RequireUser({ children }: { children: ReactElement }) {
  const { user } = useSession();
  return user ? children : <Navigate to="/" replace />;
}
