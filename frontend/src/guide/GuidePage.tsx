// База знаний в приложении.
//
// Содержимое приходит готовым из `content.json`, который собирает
// `core/guide.py`. Второго разбора формата здесь НЕТ и быть не должно:
// два разбора одного формата расходятся, и расходятся молча — этот же
// довод уже стоил проекта одного дефекта в правилах портов.
//
// Отсюда и объём этого файла: он умеет показывать разобранное, а не
// разбирать. Всё, что он знает о разметке, — это подмножество, закрытое
// проверками формата (core/test_guide.py): абзац, список, врезка кода,
// жирный, `код`, ссылка `guide:` и картинка `shot:`.

import { useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import content from "./content.json";
import styles from "../styles/guide.module.css";

interface Section { id: string; title: string; level: number }
interface Page {
  id: string;
  title: string;
  order: number;
  body: string;
  sections: Section[];
}

const PAGES = content.pages as Page[];

/** `**жирный**`, `` `код` ``, `[текст](guide:адрес)` — по одному проходу. */
function inline(text: string, key: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(guide:([a-z0-9/-]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) out.push(<strong key={`${key}-b${i}`}>{m[1]}</strong>);
    else if (m[2]) out.push(<code key={`${key}-c${i}`}>{m[2]}</code>);
    else {
      // Адрес раздела — ЧАСТЬ ПУТИ (`/guide/start/roles`), а не фрагмент
      // после решётки. Приложение раздаётся статикой и живёт на
      // HashRouter: в адресе уже есть решётка, и вторая увела бы
      // маршрутизатор в никуда — ссылка на раздел выбрасывала бы
      // читателя со страницы вместо прокрутки к ней.
      out.push(
        <Link key={`${key}-l${i}`} to={`/guide/${m[4]}`}>{m[3]}</Link>,
      );
    }
    last = m.index + m[0].length;
    i += 1;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function renderBody(body: string, pageId: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const lines = body.split("\n");
  let paragraph: string[] = [];
  let list: string[] = [];
  let code: string[] | null = null;

  const flushParagraph = (key: string) => {
    if (paragraph.length === 0) return;
    const text = paragraph.join(" ");
    out.push(<p key={key}>{inline(text, key)}</p>);
    paragraph = [];
  };
  const flushList = (key: string) => {
    if (list.length === 0) return;
    out.push(
      <ul key={key}>
        {list.map((item, i) => (
          <li key={`${key}-${i}`}>{inline(item, `${key}-${i}`)}</li>
        ))}
      </ul>,
    );
    list = [];
  };

  lines.forEach((raw, index) => {
    const key = `n${index}`;
    if (raw.startsWith("```")) {
      if (code === null) {
        flushParagraph(key);
        flushList(key);
        code = [];
      } else {
        out.push(<pre key={key}><code>{code.join("\n")}</code></pre>);
        code = null;
      }
      return;
    }
    if (code !== null) {
      code.push(raw);
      return;
    }

    const heading = raw.match(/^(#{2,3})\s+(.+?)\s*\{#([a-z0-9-]+)\}\s*$/);
    if (heading) {
      flushParagraph(key);
      flushList(key);
      const Tag = heading[1].length === 2 ? "h2" : "h3";
      // Идентификатор ставится ровно тот, что объявлен в источнике:
      // на него ссылаются извне, и вычислять его здесь заново значило бы
      // завести второй способ получить адрес.
      out.push(
        <Tag key={key} id={heading[3]} className={styles.anchored}>
          {heading[2]}
          <Link className={styles.anchorLink} to={`/guide/${pageId}/${heading[3]}`}
                aria-label="Ссылка на раздел">¶</Link>
        </Tag>,
      );
      return;
    }

    const shot = raw.match(/^!\[([^\]]*)\]\(shot:([a-z0-9-]+)\)\s*$/);
    if (shot) {
      flushParagraph(key);
      flushList(key);
      out.push(
        <figure key={key} className={styles.figure}>
          <img src={`${import.meta.env.BASE_URL}guide/${shot[2]}.png`}
               alt={shot[1]} />
          {shot[1] && <figcaption>{shot[1]}</figcaption>}
        </figure>,
      );
      return;
    }

    const bullet = raw.match(/^[*-]\s+(.*)$/);
    if (bullet) {
      flushParagraph(key);
      list.push(bullet[1]);
      return;
    }

    if (raw.trim() === "") {
      flushParagraph(key);
      flushList(key);
      return;
    }
    if (list.length > 0) {
      // Продолжение пункта списка на следующей строке.
      list[list.length - 1] += " " + raw.trim();
      return;
    }
    paragraph.push(raw.trim());
  });
  flushParagraph("tail");
  flushList("tail-list");
  return out;
}

export default function GuidePage() {
  const { pageId, sectionId } = useParams();
  const navigate = useNavigate();
  const page = PAGES.find((p) => p.id === pageId) ?? PAGES[0];

  // Прокрутка к разделу делается кодом, а не браузером: адрес раздела
  // лежит в пути, а не во фрагменте (см. комментарий про HashRouter
  // выше), и сам собой браузер туда не поедет.
  useEffect(() => {
    if (!sectionId) {
      window.scrollTo({ top: 0 });
      return;
    }
    const target = document.getElementById(sectionId);
    if (target) target.scrollIntoView({ block: "start" });
  }, [pageId, sectionId]);

  if (!page) return null;

  return (
    <div className={styles.guide}>
      <nav className={styles.toc} aria-label="Разделы базы знаний">
        <div className={styles.tocTitle}>База знаний</div>
        {PAGES.map((p) => (
          <div key={p.id}>
            <button
              className={p.id === page.id ? styles.tocActive : styles.tocItem}
              onClick={() => navigate(`/guide/${p.id}`)}
            >
              {p.title}
            </button>
            {p.id === page.id && (
              <div className={styles.tocSub}>
                {p.sections.map((s) => (
                  <Link
                    key={s.id}
                    to={`/guide/${p.id}/${s.id}`}
                    className={s.id === sectionId ? styles.tocSubActive : ""}
                  >
                    {s.title}
                  </Link>
                ))}
              </div>
            )}
          </div>
        ))}
      </nav>
      <article className={styles.article}>
        <h1>{page.title}</h1>
        {renderBody(page.body, page.id)}
      </article>
    </div>
  );
}
