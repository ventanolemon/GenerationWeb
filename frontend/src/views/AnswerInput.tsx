import { useEffect, useRef, useState } from "react";
import type { Block, InputField, TextBlock } from "../api/types";
import BlockRenderer from "../blocks/BlockRenderer";
import FormulaInput from "../formula/FormulaInput";
import { hasHoles } from "../formula/fields";
import styles from "../styles/views.module.css";

/** Чем ядро помечает пропуск в тексте условия. */
const BLANK = "___";

/**
 * Текстовый блок — с проверкой поля, а не только метки типа.
 *
 * Одного `type === "text"` мало: в `Block` есть ветка-заглушка под
 * блоки, которых фронт ещё не знает, и по метке она неотличима от
 * настоящего текста. Заглушка нужна, чтобы фронт не падал на блоках,
 * добавленных в ядро после деплоя, — но и содержимого у неё может не
 * оказаться.
 */
function asText(block: Block): TextBlock | null {
  return block.type === "text" &&
    typeof (block as TextBlock).content === "string"
    ? (block as TextBlock)
    : null;
}

/**
 * Возьмёт ли `slot_inline` условие на себя.
 *
 * Спрашивают об этом двое — сам компонент и тот, кто показывает условие
 * выше формы, — и ответить они обязаны одинаково. Разойдясь, они либо
 * покажут условие дважды, либо не покажут вовсе; второе хуже, потому
 * что задание становится нечитаемым.
 *
 * Число пропусков обязано сойтись с числом полей: поле не на своём
 * месте меняет смысл предложения, и лучше столбик полей под условием,
 * чем «She [goes] to school and [___] home» с полями вразнобой.
 */
export function inlineFitsPrompt(
  widget: string | undefined,
  fields: InputField[] | undefined,
  prompt: Block[] | undefined,
): boolean {
  if (widget !== "slot_inline" || !prompt || prompt.length === 0) return false;
  if (!fields || fields.length === 0) return false;
  const blanks = prompt.reduce((sum, block) => {
    const text = asText(block);
    return sum + (text ? text.content.split(BLANK).length - 1 : 0);
  }, 0);
  return blanks === fields.length;
}

interface Props {
  /** Имя виджета из реестра ядра (core/widgets.py). Пусто — одно поле. */
  widget?: string;
  /** Описания полей. Ответа не содержат — только подписи и подсказки. */
  fields?: InputField[];
  /**
   * Блоки условия — только для виджета `slot_inline`, который рисует
   * поля ВНУТРИ текста. Остальным раскладкам условие не нужно: его
   * показывает вызывающий, выше формы.
   */
  prompt?: Block[];
  /**
   * [строк, столбцов] — если ответ сетка. Поля идут построчно.
   *
   * Матрица и таблица тут одно и то же, и специального «матричного»
   * режима нет: сетка типизированных ячеек это сетка типизированных
   * ячеек, чем бы она ни была по смыслу.
   */
  shape?: [number, number] | null;
  /**
   * Варианты теста. Порядок приходит с сервера и устойчив между ходами —
   * перетасовывать его здесь нельзя: студент запоминает позицию.
   */
  options?: string[] | null;
  disabled?: boolean;
  /**
   * Меняется после каждого хода — сигнал очистить форму. Своего
   * представления о том, сменился ли вопрос, у компонента нет: подписи
   * полей у соседних вопросов совпадают, и по ним отличить «следующий
   * вопрос» от «попытка та же» нельзя.
   */
  resetKey?: number;
  /**
   * Ответ по полям. Ключ — имя слота; для единственного безымянного поля
   * ключ пустой. Склейку в строку здесь не делаем сознательно: значение
   * со знаком равенства или точкой с запятой сломало бы разбор в ядре,
   * то есть корректность ответа зависела бы от того, какие символы в нём
   * встретились.
   */
  onAnswer(values: Record<string, string>): void;
}

const SINGLE: InputField[] = [{ kind: "text" }];

/**
 * Поле ввода ответа — по ВИДУ спецификации, а не по типу задания.
 *
 * Ядро отвечает на два разных вопроса, и они разделены сознательно
 * (план, §3): `widget` — каким компонентом рисовать, `fields` — сколько
 * полей и что подписать. Здесь живёт реализация того, что ядро назвало
 * именем; ядро headless и про React ничего не знает, связь идёт по
 * имени — ровно как блоки связаны с фронтом полем `type`.
 *
 * Пять раскладок: варианты (тест), формула с палитрой, пропуски в
 * тексте, сетка (матрица и таблица) и поля. Первая подходящая
 * выигрывает — они не комбинируются.
 *
 * Чего здесь НЕТ: выбора НЕСКОЛЬКИХ, перетаскивания карточек.
 * Незнакомое имя виджета не ломает экран — рисуем поля по их видам,
 * потому что отказать студенту в вводе хуже, чем показать не тот
 * компонент.
 */
export default function AnswerInput({
  widget, fields, shape, options, prompt, disabled, resetKey, onAnswer,
}: Props) {
  const list = fields && fields.length > 0 ? fields : SINGLE;
  const [values, setValues] = useState<Record<string, string>>({});
  const firstRef = useRef<HTMLInputElement | null>(null);

  // Чистая форма после каждого хода и при смене состава полей.
  //
  // Оговорка, которую стоит знать: после НЕВЕРНОГО ответа с оставшимися
  // попытками форма тоже очищается, и правку приходится набирать заново.
  // Чтобы этого не делать, клиенту нужно знать, тот же это вопрос или
  // следующий, а ход сегодня такого признака не возвращает. Отдельная
  // задача — здесь важнее не оставить чужой ответ в поле нового вопроса.
  const grid = shape && shape[0] * shape[1] === list.length ? shape : null;
  const signature =
    list.map((f) => `${f.name ?? ""}:${f.kind}`).join("|") + `@${grid ?? ""}`;
  useEffect(() => {
    setValues({});
    firstRef.current?.focus();
  }, [signature, resetKey]);

  // Заполнены ДОЛЖНЫ быть все поля: набор слотов проверяется целиком, и
  // отправка половины — это потраченная попытка, а не частичный ответ.
  const filled = list.every((f) => (values[f.name ?? ""] ?? "").trim() !== "");

  function set(name: string, value: string) {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  function submit() {
    if (disabled || !filled) return;
    const payload: Record<string, string> = {};
    for (const field of list) {
      const key = field.name ?? "";
      payload[key] = (values[key] ?? "").trim();
    }
    onAnswer(payload);
    setValues({});
    firstRef.current?.focus();
  }

  if (options && options.length > 0) {
    // Тест — режим ПОКАЗА ответа, а не отдельный вид вопроса: ответом
    // уезжает текст выбранного варианта, и проверяет его та же
    // спецификация, что проверяла бы набранное руками.
    const key = list[0]?.name ?? "";
    const picked = values[key] ?? "";
    return (
      <form
        className={styles.choiceForm}
        onSubmit={(e) => {
          e.preventDefault();
          if (picked) onAnswer({ [key]: picked });
        }}
      >
        {options.map((option) => (
          <label key={option} className={styles.choiceOption}>
            <input
              type="radio"
              name={`answer-${resetKey ?? 0}`}
              checked={picked === option}
              onChange={() => set(key, option)}
              disabled={disabled}
            />
            <span>{option}</span>
          </label>
        ))}
        <button type="submit" disabled={disabled || !picked}>
          Ответить
        </button>
      </form>
    );
  }

  // Формула с палитрой. Единственная спецификация — выражение, поэтому
  // и поле одно; набор слотов палитрой не задаётся, и реестр виджетов
  // такую пару не пропустит (`core/widgets.py`).
  //
  // Проверяет ответ та же спецификация, что приняла бы набранное руками:
  // палитра — способ ВВОДА, а не отдельный вид ответа. Это то же
  // решение, что у теста и у пропусков в тексте.
  if (widget === "formula_input" && list.length === 1) {
    const key = list[0].name ?? "";
    return (
      <div className={styles.answerForm}>
        <FormulaInput
          value={values[key] ?? ""}
          onChange={(next) => set(key, next)}
          onSubmit={submit}
          disabled={disabled}
          autoFocus
          placeholder={list[0].hint || "Ответ формулой"}
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || !filled || hasHoles(values[key] ?? "")}
        >
          Ответить
        </button>
      </div>
    );
  }

  function inlineField(field: InputField, index: number) {
    const key = field.name ?? "";
    return (
      <input
        key={`f${key || index}`}
        ref={index === 0 ? firstRef : undefined}
        className={`${styles.answerInput} ${styles.blankInput}`}
        inputMode={field.kind === "number" ? "decimal" : "text"}
        value={values[key] ?? ""}
        onChange={(e) => set(key, e.target.value)}
        disabled={disabled}
        aria-label={`пропуск ${index + 1}`}
        size={Math.max(8, (values[key] ?? "").length + 2)}
        autoFocus={index === 0}
      />
    );
  }

  // Пропуски в тексте. Поля стоят на месте `___` прямо в условии —
  // единственная раскладка, которой само условие и нужно.
  //
  // Проверка при этом обычная, серверная: уезжают те же значения по
  // именам слотов, что и у полей столбиком. Ушедший вместе с
  // `sentence_fill` блок сверял ввод сам, у себя, и ради этого возил
  // правильные ответы в браузер — здесь ответов у клиента нет вовсе.
  if (inlineFitsPrompt(widget, fields, prompt)) {
    let taken = 0;
    return (
      <form
        className={styles.inlineForm}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className={styles.inlinePrompt}>
          {prompt!.map((block, bi) => {
            const text = asText(block);
            if (!text || !text.content.includes(BLANK)) {
              return <BlockRenderer key={`b${bi}`} block={block} />;
            }
            const parts: string[] = text.content.split(BLANK);
            return (
              <p key={`b${bi}`} className={styles.inlineParagraph}>
                {parts.map((segment, si) => (
                  <span key={`s${si}`}>
                    {segment}
                    {si < parts.length - 1 && inlineField(list[taken], taken++)}
                  </span>
                ))}
              </p>
            );
          })}
        </div>
        <button type="submit" disabled={disabled || !filled}>
          Ответить
        </button>
      </form>
    );
  }

  function cell(field: InputField, index: number) {
    const key = field.name ?? "";
    return (
      <input
        key={key || index}
        ref={index === 0 ? firstRef : undefined}
        className={`${styles.answerInput} ${styles.gridCell}`}
        inputMode={field.kind === "number" ? "decimal" : "text"}
        value={values[key] ?? ""}
        onChange={(e) => set(key, e.target.value)}
        disabled={disabled}
        aria-label={`строка ${Math.floor(index / grid![1]) + 1}, столбец ${
          (index % grid![1]) + 1
        }`}
        autoFocus={index === 0}
      />
    );
  }

  if (grid) {
    // У ячейки нет подписи: её подпись — место в сетке. Поэтому
    // placeholder тоже пуст, а имя для доступности собирается из
    // координат — так же, как ядро называет ячейку в разборе ошибок.
    return (
      <form
        className={styles.gridForm}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div
          className={styles.grid}
          style={{ gridTemplateColumns: `repeat(${grid[1]}, minmax(3rem, 1fr))` }}
        >
          {list.map(cell)}
        </div>
        <button type="submit" disabled={disabled || !filled}>
          Ответить
        </button>
      </form>
    );
  }

  return (
    <form
      className={list.length > 1 ? styles.answerForm : styles.inputRow}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {list.map((field, index) => {
        const key = field.name ?? "";
        return (
          <label key={key || index} className={styles.answerField}>
            {field.label && (
              <span className={styles.answerLabel}>{field.label}</span>
            )}
            <input
              ref={index === 0 ? firstRef : undefined}
              className={
                field.kind === "expression"
                  ? `${styles.answerInput} ${styles.answerInputMono}`
                  : styles.answerInput
              }
              // Числовое поле — decimal, а не number: у number браузер
              // отбрасывает запятую и «9,81» превращается в пустую строку,
              // хотя ядро запятую принимает.
              inputMode={field.kind === "number" ? "decimal" : "text"}
              value={values[key] ?? ""}
              onChange={(e) => set(key, e.target.value)}
              placeholder={field.hint || "Ваш ответ"}
              disabled={disabled}
              autoFocus={index === 0}
            />
            {/* Подсказка стоит рядом с полем ПОСТОЯННО, а не только в
                placeholder. Объявленная размерность обязательна: ответ
                «9.81» там, где ждут «9.81 м/с^2», не засчитывается. А
                placeholder исчезает с первым символом — то есть ровно
                тогда, когда подсказка нужна. */}
            {field.hint && (
              <span className={styles.answerHint}>{field.hint}</span>
            )}
          </label>
        );
      })}
      <button type="submit" disabled={disabled || !filled}>
        Ответить
      </button>
      {widget && list.length > 1 && (
        <span className={styles.answerWidgetNote}>Полей: {list.length}</span>
      )}
    </form>
  );
}
