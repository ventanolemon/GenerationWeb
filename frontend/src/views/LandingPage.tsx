import { useState } from "react";
import type { UserInfo } from "../api/types";
import AuthModal from "../components/AuthModal";
import ThemeToggle from "../components/ThemeToggle";
import styles from "../styles/landing.module.css";

interface Props {
  onLogin: (user: UserInfo | null) => void;
}

const FEATURES = [
  {
    icon: "∑",
    title: "Генератор задач",
    text: "Линейная алгебра, матанализ, физика, ОПВС — бесконечные варианты заданий с ответами в один клик.",
  },
  {
    icon: "🇬🇧",
    title: "Английский тренажёр",
    text: "Интерактивная отработка слов с проверкой опечаток и историей правильности по каждому слову.",
  },
  {
    icon: "🛠",
    title: "Конструктор заданий",
    text: "Собирайте свои задачи по физике, объединяйте разделы в группы и тесты без единой строки кода.",
  },
  {
    icon: "📄",
    title: "Экспорт в Word",
    text: "Любой набор вариантов выгружается в готовый .docx — с ответами или без, для печати и раздачи.",
  },
];

/**
 * Лендинг (вариант А): hero + карточки фич + призыв к действию.
 * Показывается до авторизации. Форма входа/регистрации открывается
 * модальным окном поверх; гостевой вход — напрямую.
 */
export default function LandingPage({ onLogin }: Props) {
  const [authTab, setAuthTab] = useState<"login" | "register" | null>(null);

  return (
    <div className={styles.page}>
      <nav className={styles.nav}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>Γ</span>
          Генератор заданий
        </div>
        <div className={styles.navActions}>
          <ThemeToggle />
          <button className={styles.navLogin} onClick={() => setAuthTab("login")}>
            Войти
          </button>
        </div>
      </nav>

      <header className={styles.hero}>
        <span className={styles.badge}>
          <span className={styles.dot} />
          Инструмент для преподавателей и студентов
        </span>
        <h1 className={styles.heroTitle}>
          Генерируйте учебные задания <em>за секунды</em>, а не за вечера
        </h1>
        <p className={styles.heroSub}>
          Математика, физика и английский — неограниченные варианты заданий,
          интерактивные тренажёры и экспорт в Word. Всё в одном рабочем месте.
        </p>
        <div className={styles.ctaRow}>
          <button className={styles.ctaPrimary} onClick={() => setAuthTab("register")}>
            Начать бесплатно
          </button>
          <button className={styles.ctaSecondary} onClick={() => onLogin(null)}>
            Попробовать как гость
          </button>
        </div>
      </header>

      <section className={styles.features}>
        {FEATURES.map((f) => (
          <article key={f.title} className={styles.card}>
            <div className={styles.cardIcon}>{f.icon}</div>
            <h3 className={styles.cardTitle}>{f.title}</h3>
            <p className={styles.cardText}>{f.text}</p>
          </article>
        ))}
      </section>

      <footer className={styles.footer}>
        Генератор заданий · образовательный инструмент
      </footer>

      {authTab && (
        <AuthModal
          initialTab={authTab}
          onLogin={onLogin}
          onClose={() => setAuthTab(null)}
        />
      )}
    </div>
  );
}
