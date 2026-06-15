// Управление темой оформления. Тема хранится в localStorage и применяется
// атрибутом data-theme на <html>. Начальное значение ставится инлайн-скриптом
// в index.html (до первой отрисовки), здесь — только чтение и переключение.

export type Theme = "dark" | "light";

const THEME_KEY = "generator_theme";
const DEFAULT_THEME: Theme = "dark";

export function getTheme(): Theme {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "light" || attr === "dark") return attr;
  return DEFAULT_THEME;
}

export function setTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* localStorage может быть недоступен — тема всё равно применится на сессию */
  }
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}
