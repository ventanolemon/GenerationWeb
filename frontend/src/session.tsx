import { createContext, useContext } from "react";
import type { Identity } from "./api/client";
import type { Role, UserInfo } from "./api/types";

/**
 * Общий контекст сессии — то, что раньше жило пропсами в App: текущий
 * пользователь (null = гость), guest-id для анонимной статистики, роль и
 * действия над сессией. Экраны за роутером берут это через useSession()
 * вместо проброски пропсов через layout/Outlet.
 */
export interface SessionValue {
  /** Профиль вошедшего пользователя; null — гостевой режим. */
  user: UserInfo | null;
  /** Стабильный id гостя (для анонимной word-статистики). */
  guestId: string;
  /** Эффективная роль. Гость и профиль без role → "student". */
  role: Role;
  /**
   * Идентичность для RBAC-эндпоинтов (X-User-Id / X-User-Role). null у
   * гостя — витрины аналитики/админки/домашек ему недоступны.
   */
  identity: Identity | null;
  /** user?.login ?? guestId — id для /generate и словарной статистики. */
  effectiveUserId: string;
  logout(): void;
  updateUser(u: UserInfo): void;
  /** Гость из профиля захотел зарегистрироваться. */
  requestRegister(): void;
}

const SessionContext = createContext<SessionValue | null>(null);

export const SessionProvider = SessionContext.Provider;

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (ctx === null) {
    throw new Error("useSession must be used within <SessionProvider>");
  }
  return ctx;
}

/** Эффективная роль из профиля (отсутствие/гость → "student"). */
export function effectiveRole(user: UserInfo | null): Role {
  return user?.role ?? "student";
}
