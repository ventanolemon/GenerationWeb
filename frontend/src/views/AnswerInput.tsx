import { useEffect, useRef, useState } from "react";
import type { InputField } from "../api/types";
import styles from "../styles/views.module.css";

interface Props {
  /** Имя виджета из реестра ядра (core/widgets.py). Пусто — одно поле. */
  widget?: string;
  /** Описания полей. Ответа не содержат — только подписи и подсказки. */
  fields?: InputField[];
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
 * Чего здесь НЕТ: палитры формул (этап 7 плана), выбора из вариантов
 * (этап 6), редактора матриц. Незнакомое имя виджета не ломает экран —
 * рисуем поля по их видам, потому что отказать студенту в вводе хуже,
 * чем показать не тот компонент.
 */
export default function AnswerInput({ widget, fields, disabled, resetKey, onAnswer }: Props) {
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
  const signature = list.map((f) => `${f.name ?? ""}:${f.kind}`).join("|");
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
