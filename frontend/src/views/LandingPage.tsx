import { useState } from "react";
import type { UserInfo } from "../api/types";
import AuthModal from "../components/AuthModal";
import ThemeToggle from "../components/ThemeToggle";
import LandingFooter from "../components/LandingFooter";
import ScrollToTop from "../components/ScrollToTop";
import styles from "../styles/landing.module.css";

interface Props {
  onLogin: (user: UserInfo | null) => void;
}

const STATS = [
  { value: "5+", label: "дисциплин" },
  { value: "7", label: "типов заданий" },
  { value: "∞", label: "вариантов" },
  { value: "0 ₽", label: "стоимость" },
];

const STEPS = [
  {
    num: "1",
    title: "Выберите раздел",
    text: "Откройте нужную дисциплину и тему из списка слева — от линейной алгебры до английских слов.",
  },
  {
    num: "2",
    title: "Сгенерируйте вариант",
    text: "Один клик — и готова уникальная задача с условием и ответом. Нужен ещё вариант? Жмите снова.",
  },
  {
    num: "3",
    title: "Выгрузите в Word",
    text: "Соберите пакет вариантов и выгрузите в .docx — с ответами или без, готовый к печати и раздаче.",
  },
];

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
  // .page имеет overflow-y: auto и является контейнером прокрутки —
  // отдаём его ScrollToTop, иначе кнопка не отследит скролл (window не двигается).
  const [pageEl, setPageEl] = useState<HTMLElement | null>(null);

  return (
    <div className={styles.page} ref={setPageEl}>
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

        <dl className={styles.stats}>
          {STATS.map((s) => (
            <div key={s.label} className={styles.stat}>
              <dt className={styles.statValue}>{s.value}</dt>
              <dd className={styles.statLabel}>{s.label}</dd>
            </div>
          ))}
        </dl>
      </header>

      <section id="features" className={styles.features}>
        {FEATURES.map((f) => (
          <article key={f.title} className={styles.card}>
            <div className={styles.cardIcon}>{f.icon}</div>
            <h3 className={styles.cardTitle}>{f.title}</h3>
            <p className={styles.cardText}>{f.text}</p>
          </article>
        ))}
      </section>

      <section id="how" className={styles.how}>
        <h2 className={styles.howTitle}>Как это работает</h2>
        <p className={styles.howSub}>Три шага от пустого экрана до готового варианта.</p>
        <div className={styles.steps}>
          {STEPS.map((step, i) => (
            <div key={step.num} className={styles.step}>
              <div className={styles.stepNum}>{step.num}</div>
              <h3 className={styles.stepTitle}>{step.title}</h3>
              <p className={styles.stepText}>{step.text}</p>
              {i < STEPS.length - 1 && <span className={styles.stepArrow} aria-hidden>→</span>}
            </div>
          ))}
        </div>
      </section>

      <LandingFooter />
      <ScrollToTop target={pageEl} />

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
