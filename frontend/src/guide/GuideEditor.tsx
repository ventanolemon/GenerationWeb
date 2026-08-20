// Правка страницы базы знаний прямо в приложении.
//
// Редактор намеренно ПРОСТОЙ: поле заголовка и поле текста в том же
// markdown, что лежит в репозитории. Визуального редактора здесь нет и
// не планируется — набор разметки закрыт (абзац, список, врезка кода,
// жирный, `код`, ссылка `guide:`, картинка `shot:`), и кнопки под каждую
// конструкцию создали бы впечатление, что можно вставить таблицу.
//
// Проверку формата делает СЛУЖБА тем же кодом, что разбирает файлы
// поставки (`core/guide.parse_text`). Здесь её нет намеренно: второй
// разбор того же формата разошёлся бы с первым, и разошёлся бы молча —
// этот довод в проекте уже стоил одного дефекта в правилах портов.
// Поэтому отказ приходит с сервера, и показывается он дословно: там
// написано «таблицы веб-клиент не показывает», а не «ошибка 400».

import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { Identity } from "../api/client";
import styles from "../styles/guide.module.css";

interface Page {
  id: string;
  title: string;
  body: string;
  edited?: boolean;
}

/** Что можно писать. Список закрыт — см. заголовок файла. */
const CHEATSHEET = [
  ["## Заголовок {#адрес}", "раздел; адрес обязателен и объявляется явно"],
  ["**жирный**, `код`", "внутри абзаца"],
  ["* пункт  /  1. пункт", "списки"],
  ["```", "врезка кода, закрывается такой же строкой"],
  ["[текст](guide:страница)", "ссылка на страницу или страница/раздел"],
  ["![подпись](shot:имя)", "снимок, порождённый scripts/guide_shots.py"],
];

export default function GuideEditor({
  page,
  identity,
  onDone,
}: {
  page: Page;
  identity: Identity;
  onDone: () => void;
}) {
  const [title, setTitle] = useState(page.title);
  const [body, setBody] = useState(page.body);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty = title !== page.title || body !== page.body;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.saveGuidePage(identity, page.id, { title, body });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    // Спрашиваем, потому что действие необратимо в одну сторону: текст
    // правки после возврата к поставочной версии взять неоткуда.
    if (!window.confirm(
      "Вернуть страницу к поставочной версии? Текст правки будет потерян.",
    )) return;
    setBusy(true);
    setError(null);
    try {
      await api.resetGuidePage(identity, page.id);
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    if (dirty && !window.confirm("Закрыть без сохранения?")) return;
    onDone();
  }

  return (
    <div className={styles.editor}>
      <div className={styles.editorHead}>
        <h1>Правка страницы</h1>
        <span className={styles.editorId}>guide/{page.id}</span>
      </div>

      <label className={styles.editorLabel}>
        Заголовок
        <input
          className={styles.editorInput}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
        />
      </label>

      <label className={styles.editorLabel}>
        Текст страницы
        <textarea
          className={styles.editorArea}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          spellCheck
        />
      </label>

      <details className={styles.cheatsheet}>
        <summary>Что можно писать</summary>
        <dl>
          {CHEATSHEET.map(([code, what]) => (
            <div key={code}>
              <dt><code>{code}</code></dt>
              <dd>{what}</dd>
            </div>
          ))}
        </dl>
        <p>
          Набор закрыт: таблицы, цитаты и картинки по пути клиент не
          показывает, и служба такую страницу не примет — вместо того
          чтобы показать её сломанной всем читателям.
        </p>
      </details>

      {error && <div className={styles.editorError}>{error}</div>}

      <div className={styles.editorActions}>
        <button type="button" onClick={cancel} disabled={busy}>
          Отмена
        </button>
        {page.edited && (
          <button type="button" onClick={reset} disabled={busy}>
            Вернуть поставочную
          </button>
        )}
        <button
          type="button"
          className={styles.editorSave}
          onClick={save}
          disabled={busy || !dirty}
        >
          {busy ? "Сохраняем…" : "Сохранить"}
        </button>
      </div>
    </div>
  );
}
