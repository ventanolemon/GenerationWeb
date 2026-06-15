// Небольшие хелперы для отображения пользователя: инициалы, цвет аватара,
// дружелюбное время последнего показа слова.

/** Палитра цветов аватара (выбирается в редакторе профиля). */
export const AVATAR_COLORS = [
  "#10b981", "#0ea5e9", "#6366f1", "#8b5cf6",
  "#ec4899", "#f59e0b", "#ef4444", "#14b8a6",
];

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0][0]!.toUpperCase();
  return (parts[0][0]! + parts[1][0]!).toUpperCase();
}

/** CSS background для аватара: сплошной цвет из профиля либо градиент по умолчанию. */
export function avatarBackground(color?: string | null): string {
  return color && color.trim()
    ? color
    : "linear-gradient(135deg, #10b981, #0ea5e9)";
}

/** «только что» / «5 мин назад» / дата для давних показов. */
export function formatLastSeen(ts: number): string {
  if (!ts || ts <= 0) return "—";
  const delta = Math.max(0, Date.now() / 1000 - ts);
  if (delta < 60) return "только что";
  if (delta < 3600) return `${Math.floor(delta / 60)} мин назад`;
  if (delta < 86400) return `${Math.floor(delta / 3600)} ч назад`;
  if (delta < 7 * 86400) return `${Math.floor(delta / 86400)} дн назад`;
  return new Date(ts * 1000).toLocaleDateString("ru-RU");
}
