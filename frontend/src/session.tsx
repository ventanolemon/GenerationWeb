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

  // ---- Режим разработчика: примерка роли ----
  //
  // `role` выше — уже ПРИМЕРЯЕМАЯ роль, если примерка включена: интерфейс
  // обязан меняться целиком, а не в тех местах, где о примерке вспомнили.
  // Настоящая роль остаётся в `trueRole` — её показывает предупреждение.

  /** Право примерять роль. Приходит с сервера (`can_try_on`), не выводится
   *  из локального профиля: иначе кнопка появляется у того, кто получит 403. */
  canTryOn: boolean;
  /** Примеряемая роль или null. */
  actingRole: Role | null;
  /** Настоящая роль, пока идёт примерка; null — примерки нет. */
  trueRole: Role | null;
  /** Включить примерку (null — выйти из неё). */
  tryOnRole(role: Role | null): void;
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

/**
 * Сессия, если она есть. `null` — экран открыт ГОСТЁМ.
 *
 * Нужен экранам, которые живут по обе стороны входа. Такой ровно один —
 * база знаний: она открыта гостю намеренно (инструкция, которую видно
 * только после входа, не помогает тому, кто не понимает, как войти), но
 * администратору на той же странице предлагает правку.
 *
 * Отдельная функция, а не `try/catch` вокруг `useSession`: бросающий
 * вариант защищает от настоящей ошибки — экран за роутером без
 * провайдера, — и глушить его на всех вызывающих ради одного значило бы
 * потерять эту защиту.
 */
export function useOptionalSession(): SessionValue | null {
  return useContext(SessionContext);
}

/** Эффективная роль из профиля (отсутствие/гость → "student"). */
export function effectiveRole(user: UserInfo | null): Role {
  return user?.role ?? "student";
}

/**
 * Ключ примерки в sessionStorage.
 *
 * Именно sessionStorage, а не localStorage: примерка умирает вместе со
 * вкладкой. Забытая на неделю примерка — худший вид невидимости, потому
 * что предупреждение перестают замечать раньше, чем выключают режим.
 * И не в состоянии React: перезагрузка страницы посреди отладки не должна
 * молча возвращать разработчика к собственной картине — это ровно та
 * путаница, ради ухода от которой примерку и делают видимой.
 */
export const ACTING_ROLE_KEY = "gw.actingRole";

export function readActingRole(): Role | null {
  try {
    const raw = sessionStorage.getItem(ACTING_ROLE_KEY);
    return raw === "student" || raw === "teacher" || raw === "admin"
      ? raw
      : null;
  } catch {
    return null;                 // приватный режим браузера — не беда
  }
}

export function writeActingRole(role: Role | null): void {
  try {
    if (role) sessionStorage.setItem(ACTING_ROLE_KEY, role);
    else sessionStorage.removeItem(ACTING_ROLE_KEY);
  } catch {
    /* примерка просто не переживёт перезагрузку — это не повод падать */
  }
}
