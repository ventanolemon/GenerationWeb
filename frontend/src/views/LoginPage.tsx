import { useState } from "react";
import type { UserInfo } from "../api/types";
import { api, ApiError } from "../api/client";
import styles from "../styles/login.module.css";

interface Props {
  onLogin: (user: UserInfo | null) => void;
}

/**
 * Экран входа. Повторяет логику AuthWindow из десктопной версии:
 *   - форма логин/пароль → POST /api/auth/login
 *   - кнопка «Гостевой вход» → onLogin(null)
 */
export default function LoginPage({ onLogin }: Props) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    if (!login.trim() || !password) {
      setError("Введите логин и пароль.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const user = await api.login(login.trim(), password);
      onLogin(user);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Неверный логин или пароль.");
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.overlay}>
      <div className={styles.card}>
        <h1 className={styles.title}>Генератор заданий</h1>
        <form onSubmit={handleLogin} className={styles.form}>
          <label className={styles.label}>
            Логин
            <input
              className={styles.input}
              type="text"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              autoFocus
              autoComplete="username"
            />
          </label>
          <label className={styles.label}>
            Пароль
            <input
              className={styles.input}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error && <div className={styles.error}>{error}</div>}
          <div className={styles.btns}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>
              {loading ? "Вход…" : "Войти"}
            </button>
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={() => onLogin(null)}
              disabled={loading}
            >
              Гостевой вход
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
