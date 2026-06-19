import { useEffect, useState } from "react";
import styles from "../styles/scroll-to-top.module.css";

interface Props {
  // Контейнер, прокрутку которого отслеживаем. Если не передан — window.
  target?: HTMLElement | null;
  // Порог появления кнопки в пикселях прокрутки.
  threshold?: number;
}

/**
 * Плавающая кнопка «наверх». Появляется после прокрутки на `threshold`
 * пикселей и скроллит свой целевой контейнер к началу. Лендинг скроллит
 * window; основное приложение прокручивает <main>, поэтому target
 * параметризован.
 */
export default function ScrollToTop({ target, threshold = 400 }: Props) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el: HTMLElement | Window = target ?? window;
    const getScroll = () =>
      target ? target.scrollTop : window.scrollY;

    function onScroll() {
      setVisible(getScroll() > threshold);
    }

    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, [target, threshold]);

  function scrollUp() {
    const el: HTMLElement | Window = target ?? window;
    el.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <button
      type="button"
      className={`${styles.button} ${visible ? styles.visible : ""}`}
      onClick={scrollUp}
      aria-label="Наверх"
      title="Наверх"
    >
      ↑
    </button>
  );
}
