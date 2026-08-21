import { useState } from "react";
import { Link } from "react-router-dom";
import type { UserInfo } from "../api/types";
import AuthModal from "../components/AuthModal";
import ThemeToggle from "../components/ThemeToggle";
import LandingFooter from "../components/LandingFooter";
import ScrollToTop from "../components/ScrollToTop";
import styles from "../styles/landing.module.css";

interface Props {
  onLogin: (user: UserInfo | null) => void;
}

/**
 * Числа — ЗАМЕРЕННЫЕ, а не круглые.
 *
 * «5+ дисциплин» и «∞ вариантов» стояли здесь раньше и не говорили
 * ничего: первое звучит как обещание, второе как реклама. Числа ниже
 * можно проверить прогоном, и они сообщают о системе больше, чем
 * прилагательные.
 */
const STATS = [
  { value: "6", label: "дисциплин", hint: "линал, матан, физика, ОПВС, информатика, английский" },
  { value: "145", label: "операций языка", hint: "из них собирается описание задания" },
  { value: "8", label: "видов ответа", hint: "число, текст, выражение, логика, уравнение, вывод программы, произношение, набор полей" },
  { value: "4098", label: "автопроверок", hint: "прогон сервера, настольного приложения и веб-клиента" },
];

const FEATURES = [
  {
    icon: "∑",
    title: "Варианты, а не задачи",
    text: "Раздел порождает столько вариантов, сколько нужно: у каждого студента свой набор чисел при одинаковых темах. Списать не у кого, проверять — по одному правилу.",
  },
  {
    icon: "◇",
    title: "Задание собирается схемой",
    text: "Описание задания — граф из операций, а не код. Типы связей проверяются при сборке: несовместимое соединение не дают сделать, а не роняют при выдаче.",
  },
  {
    icon: "≡",
    title: "Проверка по смыслу",
    text: "Ответ хранится данными с правилом сравнения, а не строкой. «2,5» и «2.5», «x²−1» и «(x−1)(x+1)» — один ответ; разные термины словаря — разные, даже если отличаются одной буквой.",
  },
  {
    icon: "📄",
    title: "Выгрузка в Word",
    text: "Число вариантов и куда девать ответы: под заданием, отрывным ключом в конце варианта, пачкой в конце файла или совсем убрать. Последнее — лист для раздачи.",
  },
  {
    icon: "🎧",
    title: "Английский вслух",
    text: "Словарный диктант, разбор транскрипции и произношение с записью голоса: система отвечает, на какое слово словаря запись похожа больше — или честно отказывается судить.",
  },
  {
    icon: "⛰",
    title: "Работает без сети",
    text: "Настольное приложение генерирует и проверяет автономно, копит попытки и обменивается ими с сервером, когда сеть появится. Аудитория без интернета — обычный случай, а не авария.",
  },
];

/**
 * Раздел «проверка по смыслу» — единственное место лендинга с примерами.
 *
 * Он здесь потому, что это и есть отличие системы, и объяснить его
 * прилагательными нельзя: «умная проверка» ничего не значит, а две
 * записи одного ответа рядом — значат.
 */
const EQUALITY = [
  {
    kind: "Число",
    same: ["2,5", "2.5", "2.50"],
    different: ["25", "2.5 кг"],
    note: "запятая и точка — одно; размерность, если её спросили, — часть ответа",
  },
  {
    kind: "Выражение",
    same: ["x²−1", "(x−1)(x+1)"],
    different: ["x²+1"],
    note: "сравниваются выражения, а не их запись",
  },
  {
    kind: "Термин",
    same: ["hyperlnk", "hyperlink"],
    different: ["LAN", "WAN"],
    note: "опечатка прощается ровно до тех пор, пока рядом нет другого термина словаря",
  },
];

const STEPS = [
  {
    num: "1",
    title: "Открыть раздел",
    text: "Дисциплина и тема слева. Внутри — либо готовое задание, либо тренажёр, либо и то и другое: смотреть и решать переключается.",
  },
  {
    num: "2",
    title: "Собрать варианты",
    text: "Один клик — один вариант, или сразу пачка нужного размера. Долгая сборка показывает ход и её можно прервать, не потеряв собранное.",
  },
  {
    num: "3",
    title: "Выдать или напечатать",
    text: "Группе — домашним заданием, каждому свой вариант и своя статистика. На бумагу — выгрузкой в Word с выбранным размещением ответов.",
  },
];

const AUDIENCE = [
  {
    who: "Преподавателю",
    items: [
      "собрать задание схемой, без программирования",
      "выдать группе — каждому свой вариант",
      "увидеть, где группа спотыкается, по разделам",
      "напечатать лист с отрывным ключом",
    ],
  },
  {
    who: "Студенту",
    items: [
      "решать с проверкой, а не сверяться с ответом в конце",
      "видеть, ПОЧЕМУ не принято: не та размерность, не та форма",
      "тренировать английские слова и произношение",
      "работать без интернета в настольной версии",
    ],
  },
];

/**
 * Лендинг: hero → что умеет → чем отличается проверка → как это работает
 * → кому что → призыв.
 *
 * Показывается до авторизации. Форма входа/регистрации открывается
 * модальным окном поверх; гостевой вход — напрямую.
 *
 * Отдельно: ссылка на базу знаний стоит в навигации, а не только в
 * подвале. База открыта гостю намеренно — инструкция, которую видно
 * только после входа, не помогает тому, кто как раз и не понимает, как
 * войти, — но до этой правки попасть в неё с лендинга было НЕОТКУДА, и
 * намерение оставалось намерением.
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
          <Link className={styles.navLink} to="/guide">
            База знаний
          </Link>
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
          Шесть дисциплин, задание собирается схемой, ответ проверяется по
          смыслу, а не по совпадению строк. Вариантов столько, сколько
          студентов в группе.
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
            <div key={s.label} className={styles.stat} title={s.hint}>
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

      <section id="equality" className={styles.equality}>
        <h2 className={styles.howTitle}>Что значит «проверка по смыслу»</h2>
        <p className={styles.howSub}>
          Правильный ответ хранится не строкой, а данными с правилом
          сравнения. Правило знает, что за величина перед ним.
        </p>
        <div className={styles.equalityGrid}>
          {EQUALITY.map((row) => (
            <article key={row.kind} className={styles.equalityCard}>
              <h3 className={styles.equalityKind}>{row.kind}</h3>
              <p className={styles.equalityLine}>
                <span className={styles.same}>одно и то же</span>
                {row.same.map((v) => (
                  <code key={v} className={styles.sample}>{v}</code>
                ))}
              </p>
              <p className={styles.equalityLine}>
                <span className={styles.diff}>разное</span>
                {row.different.map((v) => (
                  <code key={v} className={styles.sample}>{v}</code>
                ))}
              </p>
              <p className={styles.equalityNote}>{row.note}</p>
            </article>
          ))}
        </div>
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

      <section id="audience" className={styles.audience}>
        {AUDIENCE.map((group) => (
          <article key={group.who} className={styles.audienceCard}>
            <h3 className={styles.audienceWho}>{group.who}</h3>
            <ul className={styles.audienceList}>
              {group.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        ))}
      </section>

      <section className={styles.finalCta}>
        <h2 className={styles.howTitle}>Посмотреть можно без регистрации</h2>
        <p className={styles.howSub}>
          Гостевой вход открывает генератор целиком. База знаний — тоже:
          читать её можно, не заводя учётной записи.
        </p>
        <div className={styles.ctaRow}>
          <button className={styles.ctaPrimary} onClick={() => onLogin(null)}>
            Войти как гость
          </button>
          <Link className={styles.ctaSecondary} to="/guide">
            Открыть базу знаний
          </Link>
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
