import { useEffect, useMemo, useState } from "react";
import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import type { Role, UserInfo } from "./api/types";
import { SessionProvider, effectiveRole, useSession } from "./session";
import type { SessionValue } from "./session";
import LandingPage from "./views/LandingPage";
import AppLayout from "./layouts/AppLayout";
import GeneratorPage from "./pages/GeneratorPage";
import AnalyticsPage from "./pages/AnalyticsPage";
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

  useEffect(() => {
    const stored = loadStoredUser();
    if (stored !== null || localStorage.getItem(USER_STORAGE_KEY) === "guest") {
      setUser(stored);
      setAuthenticated(true);
    }
    setAuthChecked(true);
  }, []);

  function handleLogin(userInfo: UserInfo | null) {
    setUser(userInfo);
    setAuthenticated(true);
    localStorage.setItem(
      USER_STORAGE_KEY,
      userInfo ? JSON.stringify(userInfo) : "guest",
    );
  }

  function handleLogout() {
    setAuthenticated(false);
    setUser(null);
    localStorage.removeItem(USER_STORAGE_KEY);
  }

  function updateUser(updated: UserInfo) {
    setUser(updated);
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(updated));
  }

  const session = useMemo<SessionValue | null>(() => {
    if (!authenticated) return null;
    const role = effectiveRole(user);
    return {
      user,
      guestId,
      role,
      identity: user ? { login: user.login, role } : null,
      effectiveUserId: user?.login ?? guestId,
      logout: handleLogout,
      updateUser,
      // Регистрация из профиля обрабатывается в AppLayout (открывает
      // AuthModal); поле требуется контрактом сессии — здесь no-op.
      requestRegister: () => {},
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticated, user, guestId]);

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
