import {
  APP_NAME,
  APP_VERSION,
  APP_YEAR,
  DISCIPLINES,
  LINKS,
  TECH_STACK,
} from "../meta";
import styles from "../styles/landing-footer.module.css";

/**
 * Многоколоночный подвал лендинга в стиле «серьёзного» продукта:
 * брендовая колонка с техническим стеком, навигация по якорям,
 * перечень дисциплин и нижняя полоса с копирайтом и версией.
 */
export default function LandingFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.grid}>
        <div className={styles.brandCol}>
          <div className={styles.brand}>
            <span className={styles.brandMark}>Γ</span>
            <span className={styles.brandName}>{APP_NAME}</span>
          </div>
          <p className={styles.tagline}>
            Образовательный инструмент для генерации учебных заданий
            по математике, физике и иностранным языкам.
          </p>
          <div className={styles.badges}>
            {TECH_STACK.map((t) => (
              <span key={t} className={styles.badge}>
                {t}
              </span>
            ))}
          </div>
        </div>

        <nav className={styles.linkCol} aria-label="Возможности">
          <h4 className={styles.colTitle}>Возможности</h4>
          <a href="#features" className={styles.link}>
            Генератор задач
          </a>
          <a href="#how" className={styles.link}>
            Как это работает
          </a>
          <a href="#features" className={styles.link}>
            Экспорт в Word
          </a>
          <a href="#features" className={styles.link}>
            Интерактивные тренажёры
          </a>
        </nav>

        <nav className={styles.linkCol} aria-label="Дисциплины">
          <h4 className={styles.colTitle}>Дисциплины</h4>
          {DISCIPLINES.map((d) => (
            <span key={d} className={styles.linkStatic}>
              {d}
            </span>
          ))}
        </nav>

        <nav className={styles.linkCol} aria-label="О проекте">
          <h4 className={styles.colTitle}>О проекте</h4>
          <span className={styles.linkStatic}>Учебный проект</span>
          <span className={styles.linkStatic}>Версия {APP_VERSION}</span>
          {LINKS.docs && (
            <a href={LINKS.docs} className={styles.link}>
              Документация
            </a>
          )}
          {LINKS.repo && (
            <a
              href={LINKS.repo}
              className={styles.link}
              target="_blank"
              rel="noreferrer"
            >
              Исходный код
            </a>
          )}
        </nav>
      </div>

      <div className={styles.bottomBar}>
        <span>
          © {APP_YEAR} {APP_NAME}. Все права защищены.
        </span>
        <span className={styles.version}>v{APP_VERSION}</span>
      </div>
    </footer>
  );
}
