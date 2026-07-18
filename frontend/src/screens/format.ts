// Форматтеры и русские подписи для экранов-витрин. Держим в одном месте,
// чтобы карточки/таблицы/пилюли говорили одинаково.

import type { Role } from "../api/types";

export const pct = (x: number | null | undefined): string =>
  x == null ? "—" : `${Math.round(x * 100)}%`;

export const num = (x: number): string => x.toLocaleString("ru-RU");

/** Доля 0..1 → «+12%» / «−4%» со знаком (для дельт периода). */
export function signedPct(x: number | null): string {
  if (x == null) return "—";
  const v = Math.round(x * 100);
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v)}%`;
}

/** Разница долей верных ответов в процентных пунктах. */
export function signedPp(x: number | null): string {
  if (x == null) return "—";
  const v = Math.round(x * 100);
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v)} п.п.`;
}

/** ISO-строка → «дд.мм» (для оси/срока), пусто → «—». */
export function shortDate(iso: string): string {
  if (!iso) return "—";
  const d = iso.slice(0, 10).split("-");
  return d.length === 3 ? `${d[2]}.${d[1]}` : iso;
}

/** epoch-секунды → «ГГГГ-ММ-ДД» (срок домашки). null → «без срока». */
export function fmtDue(due: number | null): string {
  if (due == null) return "без срока";
  return new Date(due * 1000).toISOString().slice(0, 10);
}

// ---------- Русские подписи enum'ов из API ----------

export const RU_ROLE: Record<Role, string> = {
  student: "студент",
  teacher: "преподаватель",
  admin: "администратор",
};

export const RU_TASK_TYPE: Record<"graph" | "test", string> = {
  graph: "Граф",
  test: "Тест",
};

type Diff = "easy" | "medium" | "hard";
export const RU_DIFFICULTY: Record<Diff, string> = {
  easy: "лёгкое",
  medium: "среднее",
  hard: "трудное",
};
// Статусный цвет (pill-класс) — отдельно от акцента, как требует dataviz.
export const DIFFICULTY_PILL: Record<Diff, "ok" | "warn" | "bad"> = {
  easy: "ok",
  medium: "warn",
  hard: "bad",
};

type Status = "struggling" | "steady" | "strong";
export const RU_STATUS: Record<Status, string> = {
  struggling: "отстаёт",
  steady: "ровно",
  strong: "уверенно",
};
export const STATUS_PILL: Record<Status, "ok" | "warn" | "bad"> = {
  struggling: "bad",
  steady: "warn",
  strong: "ok",
};
