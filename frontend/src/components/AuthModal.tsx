import { useState } from "react";
import type { UserInfo } from "../api/types";
import { api, ApiError } from "../api/client";
import Modal from "./Modal";
import styles from "../styles/login.module.css";

interface Props {
  initialTab?: AuthTab;
  onLogin: (user: UserInfo | null) => void;
  onClose: () => void;
}

type AuthTab = "login" | "register";

export default function AuthModal({ initialTab = "login", onLogin, onClose }: Props) {
  const [tab, setTab] = useState<AuthTab>(initialTab);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Вход
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");

  // Регистрация
  const [regLogin, setRegLogin] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regPassword2, setRegPassword2] = useState("");
  const [regFio, setRegFio] = useState("");
  const [regGroup, setRegGroup] = useState("");
  const [regEmail, setRegEmail] = useState("");

  function switchTab(t: AuthTab) {
    setTab(t);
    setError(null);
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    if (!login.trim() || !password) { setError("Введите логин и пароль."); return; }
    setLoading(true);
    setError(null);
    try {
      const user = await api.login(login.trim(), password);
      onLogin(user);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Неверный логин или пароль."
          : err instanceof Error ? err.message : String(err)
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    if (!regLogin.trim()) { setError("Введите логин."); return; }
    if (regPassword.length < 4) { setError("Пароль должен быть не менее 4 символов."); return; }
    if (regPassword !== regPassword2) { setError("Пароли не совпадают."); return; }
    if (!regFio.trim()) { setError("Введите имя."); return; }

    setLoading(true);
    setError(null);
    try {
      const user = await api.register({
        login: regLogin.trim(),
        password: regPassword,
        fio: regFio.trim(),
        group: regGroup.trim(),
        email: regEmail.trim(),
      });
      onLogin(user);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? `Логин «${regLogin}» уже занят. Выберите другой.`
          : err instanceof Error ? err.message : String(err)
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title="Вход в систему" onClose={onClose} width={420}>
      <div className={styles.tabs}>
        <button
          className={`${styles.tab} ${tab === "login" ? styles.tabActive : ""}`}
          onClick={() => switchTab("login")}
        >
          Вход
        </button>
        <button
          className={`${styles.tab} ${tab === "register" ? styles.tabActive : ""}`}
          onClick={() => switchTab("register")}
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
        <form onSubmit={handleRegister} className={styles.form}>
          <label className={styles.label}>
            Логин *
            <input
              className={styles.input}
              type="text"
              value={regLogin}
              onChange={(e) => setRegLogin(e.target.value)}
              autoFocus
              autoComplete="username"
              placeholder="только латиница, цифры, _ - ."
            />
          </label>
          <label className={styles.label}>
            Имя (ФИО) *
            <input
              className={styles.input}
              type="text"
              value={regFio}
              onChange={(e) => setRegFio(e.target.value)}
              autoComplete="name"
              placeholder="Иванов Иван Иванович"
            />
          </label>
          <label className={styles.label}>
            Группа
            <input
              className={styles.input}
              type="text"
              value={regGroup}
              onChange={(e) => setRegGroup(e.target.value)}
              placeholder="ИВТ-21"
            />
          </label>
          <label className={styles.label}>
            Email
            <input
              className={styles.input}
              type="email"
              value={regEmail}
              onChange={(e) => setRegEmail(e.target.value)}
              autoComplete="email"
              placeholder="необязательно"
            />
          </label>
          <label className={styles.label}>
            Пароль *
            <input
              className={styles.input}
              type="password"
              value={regPassword}
              onChange={(e) => setRegPassword(e.target.value)}
              autoComplete="new-password"
            />
          </label>
          <label className={styles.label}>
            Повторите пароль *
            <input
              className={styles.input}
              type="password"
              value={regPassword2}
              onChange={(e) => setRegPassword2(e.target.value)}
              autoComplete="new-password"
            />
          </label>
          {error && <div className={styles.error}>{error}</div>}
          <button type="submit" className={styles.btnPrimary} disabled={loading}>
            {loading ? "Регистрация…" : "Зарегистрироваться"}
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
      )}
    </Modal>
  );
}
