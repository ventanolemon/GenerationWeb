import { useState } from "react";
import { getTheme, toggleTheme, type Theme } from "../theme";
import styles from "../styles/theme-toggle.module.css";

/**
 * Кнопка-переключатель темы (☀ / ☾). Локальный стейт нужен только для
 * перерисовки иконки — источник правды живёт в data-theme на <html>.
 */
export default function ThemeToggle({ className }: { className?: string }) {
  const [theme, setLocalTheme] = useState<Theme>(getTheme);

  function handleToggle() {
    setLocalTheme(toggleTheme());
  }

  const isDark = theme === "dark";
  return (
    <button
      type="button"
      className={`${styles.toggle} ${className ?? ""}`}
      onClick={handleToggle}
      title={isDark ? "Светлая тема" : "Тёмная тема"}
      aria-label="Переключить тему"
    >
      <span className={styles.icon}>{isDark ? "☀" : "☾"}</span>
      <span className={styles.label}>{isDark ? "Светлая" : "Тёмная"}</span>
    </button>
  );
}
