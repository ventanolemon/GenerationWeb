import { useCallback, useEffect, useMemo, useRef } from "react";
import katex from "katex";
import { HOLE, hasHoles, insert, insertRow, nextField } from "./fields";
import { ADD_ROW, TEMPLATES, type Template } from "./templates";
import styles from "../styles/formula.module.css";

/**
 * Поле ввода формулы с палитрой и живым предпросмотром (план, §10.2).
 *
 * Три решения плана, которые здесь и живут:
 *
 * **Палитра вставляет шаблон с дырками.** Нажали «дробь» — получили
 * `\frac{▯}{▯}`, курсор в первой, Tab переводит во вторую.
 *
 * **Явный и неявный ввод — один движок.** Под кнопками обычная строка,
 * её же можно набрать руками, её же разбирает и проверяет ядро.
 * Отличается только наличием кнопок, поэтому «явный формат» стоит почти
 * ничего сверх неявного.
 *
 * **Живой предпросмотр — главный учитель.** Тот, кто не знает LaTeX (а
 * палитра ровно для него), понимает, что набрал, только увидев это
 * набранным. Рисуется тем же KaTeX, что и условие, — значит, увиденное
 * при вводе и есть то, что покажут потом.
 *
 * Поле остаётся полем после заполнения
 * ------------------------------------
 * Дырка исчезает с первым введённым символом, но поле — это не дырка, а
 * группа в скобках (см. `fields.ts`). Поэтому Tab возвращает и в уже
 * заполненный числитель, и содержимое там выделяется целиком: поправить
 * дробь можно, не стирая её и не набирая заново.
 */
export default function FormulaInput({
  value,
  onChange,
  onSubmit,
  disabled,
  autoFocus,
  placeholder,
}: {
  value: string;
  onChange(next: string): void;
  onSubmit?(): void;
  disabled?: boolean;
  autoFocus?: boolean;
  placeholder?: string;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  /**
   * Куда поставить выделение, когда React положит в поле новый текст.
   *
   * Ref, а не состояние, и снимается СИНХРОННО. С состоянием здесь
   * гонка, которую видно на быстром наборе: пока React не обработал
   * сброс, эффект успевает сработать ещё раз на изменившемся тексте и
   * возвращает каретку назад. Каждый следующий символ встаёт на то же
   * место, и «z=3» набирается как «3=z».
   */
  const pending = useRef<{ start: number; end: number } | null>(null);

  // Без списка зависимостей: сработать надо после ЛЮБОЙ перерисовки,
  // изменившей текст, а сторож на ref делает это дешёвым.
  useEffect(() => {
    const target = pending.current;
    if (!target || !inputRef.current) return;
    pending.current = null;
    inputRef.current.focus();
    inputRef.current.setSelectionRange(target.start, target.end);
  });

  const apply = useCallback(
    (template: string) => {
      const el = inputRef.current;
      const from = el ? el.selectionStart ?? value.length : value.length;
      const to = el ? el.selectionEnd ?? from : from;
      const result = insert(value, from, to, template);
      onChange(result.text);
      pending.current = result.select;
    },
    [onChange, value],
  );

  const addRow = useCallback(() => {
    const el = inputRef.current;
    const caret = el ? el.selectionEnd ?? value.length : value.length;
    const result = insertRow(value, caret, ADD_ROW.latex);
    onChange(result.text);
    pending.current = result.select;
  }, [onChange, value]);

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    const el = event.currentTarget;
    if (event.key === "Tab") {
      const caret = event.shiftKey
        ? el.selectionStart ?? 0
        : el.selectionEnd ?? 0;
      const target = nextField(value, caret, event.shiftKey ? -1 : 1);
      // Переходить некуда — Tab остаётся Tab'ом и уводит фокус дальше.
      // Иначе с клавиатуры из формулы не выбраться, а это уже не
      // удобство, а недоступность.
      if (target) {
        event.preventDefault();
        // Прямо здесь, а не через `pending`: текст не менялся, в поле
        // уже лежит то, к чему относятся координаты, и ждать
        // перерисовки нечего.
        //
        // Содержимое выделяется ЦЕЛИКОМ: в пустое поле так попадает
        // первый символ вместо дырки, а в заполненное — правка одним
        // движением, ради которой поля и переживают заполнение.
        el.setSelectionRange(target.start, target.end);
      }
      return;
    }
    if (event.key === "Enter" && onSubmit) {
      event.preventDefault();
      onSubmit();
    }
  }

  const preview = useMemo(() => renderPreview(value), [value]);
  const unfilled = hasHoles(value);

  return (
    <div className={styles.wrap}>
      <div className={styles.palette} role="toolbar" aria-label="Конструкции">
        {TEMPLATES.map((t) => (
          <PaletteButton
            key={t.title}
            template={t}
            disabled={disabled}
            onPick={apply}
          />
        ))}
        <span className={styles.paletteGap} />
        <PaletteButton
          template={ADD_ROW}
          disabled={disabled}
          onPick={addRow}
        />
      </div>

      <input
        ref={inputRef}
        className={styles.source}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={disabled}
        placeholder={placeholder || "Ответ формулой"}
        autoFocus={autoFocus}
        spellCheck={false}
        autoComplete="off"
        aria-label="Формула"
      />

      <div className={styles.preview} aria-live="polite">
        {value.trim() === "" ? (
          <span className={styles.previewEmpty}>Здесь появится формула</span>
        ) : preview === null ? (
          // Незаконченная формула при наборе — обычное дело, а не ошибка:
          // «\frac{» невозможно нарисовать, но человек как раз его и
          // печатает. Ругаться на каждый промежуточный символ значило бы
          // мигать красным всё время набора.
          <span className={styles.previewPending}>…</span>
        ) : (
          <span dangerouslySetInnerHTML={{ __html: preview }} />
        )}
      </div>

      {unfilled && (
        <p className={styles.hint}>
          Заполните пустые места ({HOLE}) — Tab переводит к следующему.
        </p>
      )}
    </div>
  );
}

function PaletteButton({
  template,
  disabled,
  onPick,
}: {
  template: Template;
  disabled?: boolean;
  onPick(latex: string): void;
}) {
  const label = useMemo(() => {
    try {
      return katex.renderToString(template.label, {
        throwOnError: true,
        strict: false,
      });
    } catch {
      return null;
    }
  }, [template.label]);

  return (
    <button
      type="button"
      className={styles.key}
      title={template.title}
      aria-label={template.title}
      disabled={disabled}
      // Кнопка не должна забирать фокус: иначе после вставки курсор
      // оказывается на ней, а не в поле, и следующий символ уходит в
      // никуда.
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => onPick(template.latex)}
    >
      {label === null ? (
        <span>{template.title}</span>
      ) : (
        <span dangerouslySetInnerHTML={{ __html: label }} />
      )}
    </button>
  );
}

/**
 * Предпросмотр набранного. `null` — сейчас нарисовать нельзя.
 *
 * Дырка заменяется на `\square`: у самого символа `▯` в шрифтах KaTeX
 * нет метрик, и он вылезал бы предупреждением в консоли и пустым местом
 * на экране — ровно там, где пустое место надо ПОКАЗАТЬ.
 */
function renderPreview(value: string): string | null {
  const text = value.split(HOLE).join("\\square");
  if (text.trim() === "") return null;
  try {
    return katex.renderToString(text, {
      displayMode: true,
      throwOnError: true,
      strict: false,
    });
  } catch {
    return null;
  }
}
