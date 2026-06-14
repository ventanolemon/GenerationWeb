import { useState } from "react";
import type { UserInfo } from "../api/types";
import { api, ApiError } from "../api/client";
import Modal from "./Modal";
import styles from "../styles/login.module.css";

interface Props {
  /** С какой вкладки открыть: вход или регистрация. */
  initialTab?: AuthTab;
  onLogin: (user: UserInfo | null) => void;
  onClose: () => void;
}

type AuthTab = "login" | "register";

/**
 * Модальное окно авторизации поверх лендинга.
 *
 * Вкладка «Вход» — рабочая форма: POST /api/auth/login (проверка в таблице
 * users десктопной БД). Вкладка «Регистрация» — информационная: учётные
 * записи в этой системе заводит администратор, поэтому вместо неработающей
 * формы показываем пояснение и предлагаем гостевой вход.
 */
export default function AuthModal({ initialTab = "login", onLogin, onClose }: Props) {
  const [tab, setTab] = useState<AuthTab>(initialTab);
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
    <Modal title="Вход в систему" onClose={onClose} width={400}>
      <div className={styles.tabs}>
        <button
          className={`${styles.tab} ${tab === "login" ? styles.tabActive : ""}`}
          onClick={() => { setTab("login"); setError(null); }}
        >
          Вход
        </button>
        <button
          className={`${styles.tab} ${tab === "register" ? styles.tabActive : ""}`}
          onClick={() => { setTab("register"); setError(null); }}
        >
          Регистрация
        </button>
      </div>

      {tab === "login" ? (
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
          <button type="submit" className={styles.btnPrimary} disabled={loading}>
            {loading ? "Вход…" : "Войти"}
          </button>
          <div className={styles.divider}>или</div>
          <button
            type="button"
            className={styles.btnGuest}
            onClick={() => onLogin(null)}
            disabled={loading}
          >
            Продолжить как гость
          </button>
        </form>
      ) : (
        <div className={styles.form}>
          <div className={styles.infoPanel}>
            Учётные записи в системе выдаёт <strong>администратор</strong> вашего
            учебного заведения. Если у вас уже есть логин — перейдите на вкладку{" "}
            <strong>«Вход»</strong>.
            <br />
            <br />
            Хотите просто попробовать? Гостевой режим даёт полный доступ к
            генератору; история ответов сохраняется только в этом браузере.
          </div>
          <button
            type="button"
            className={styles.btnPrimary}
            onClick={() => onLogin(null)}
          >
            Попробовать как гость
          </button>
        </div>
      )}
    </Modal>
  );
}
