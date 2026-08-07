/**
 * Поля формулы: где в LaTeX-строке стоят места, которые заполняют.
 *
 * План (§10.2): палитра вставляет ШАБЛОН С ДЫРКАМИ — нажали «дробь»,
 * получили `\frac{▯}{▯}`, курсор в первой, Tab переводит во вторую.
 * Под капотом при этом обычная строка, которую разбирает и проверяет
 * ядро, — никакого дерева и никаких невидимых меток, иначе они уехали
 * бы в ответ.
 *
 * Ключевое требование — **поле остаётся полем и после заполнения**.
 * Дырка `▯` исчезает с первым введённым символом, и если бы навигация
 * искала только дырки, вернуться в уже заполненный числитель было бы
 * нечем: пришлось бы стирать всё и набирать заново. Поэтому поле — это
 * не дырка, а ГРУППА В ФИГУРНЫХ СКОБКАХ; дырка лишь показывает, что
 * группа пуста.
 *
 * Отсюда одно требование к шаблонам (`templates.ts`): каждая дырка в
 * них обёрнута собственной парой скобок. Лишние скобки в LaTeX ничего
 * не меняют — `{n}` и `n` рисуются одинаково, — зато после заполнения
 * от поля остаётся след, по которому в него можно вернуться.
 */

/** Символ пустого места. Один на всю палитру — его же ищет проверка. */
export const HOLE = "▯";

export interface Field {
  /** Индекс первого символа содержимого (не скобки). */
  start: number;
  /** Индекс за последним символом содержимого. */
  end: number;
}

/**
 * Скобочные группы, которые полями НЕ являются: имя окружения в
 * `\begin{cases}` — это не место для ответа, а часть конструкции.
 */
const ENVIRONMENT = /\\(begin|end)$/;

/**
 * Все поля строки по порядку.
 *
 * Берутся ЛИСТОВЫЕ группы — те, внутри которых нет вложенных. У
 * `\frac{\sqrt{2}}{3}` это `2` и `3`, а не «весь числитель»: поле в
 * представлении пишущего — то, куда ставится курсор, а числитель
 * целиком выделяется мышью и без нашей помощи.
 *
 * Отдельно стоящая дырка (автор набрал её руками или шаблон оказался
 * без скобок) тоже поле — иначе в неё нельзя было бы попасть Tab'ом.
 */
export function fields(text: string): Field[] {
  const out: Field[] = [];
  const stack: number[] = [];
  const nested = new Set<number>();

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "\\") {
      i++; // экранированная скобка `\{` — не группа, а символ
      continue;
    }
    if (ch === "{") {
      if (stack.length > 0) nested.add(stack[stack.length - 1]);
      stack.push(i);
      continue;
    }
    if (ch === "}" && stack.length > 0) {
      const open = stack.pop()!;
      if (nested.has(open)) continue;               // не лист
      if (ENVIRONMENT.test(text.slice(0, open))) continue;
      out.push({ start: open + 1, end: i });
    }
  }

  // Дырки вне всяких скобок.
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== HOLE) continue;
    if (out.some((f) => f.start <= i && i < f.end)) continue;
    out.push({ start: i, end: i + 1 });
  }

  out.sort((a, b) => a.start - b.start || a.end - b.end);
  return out;
}

/** Есть ли ещё незаполненные места. */
export function hasHoles(text: string): boolean {
  return text.includes(HOLE);
}

/**
 * Поле, в котором стоит курсор, или ближайшее следующее.
 *
 * `-1` — полей нет вовсе.
 */
export function fieldAt(text: string, caret: number): number {
  const all = fields(text);
  for (let i = 0; i < all.length; i++) {
    if (caret >= all[i].start && caret <= all[i].end) return i;
  }
  return -1;
}

/**
 * Куда перейти по Tab (`step = +1`) или Shift+Tab (`step = -1`).
 *
 * Возвращает поле или `null`, если переходить некуда — тогда Tab
 * обязан остаться Tab'ом и увести фокус с поля, иначе с клавиатуры из
 * формулы не выбраться, а это уже недоступность, а не удобство.
 */
export function nextField(
  text: string,
  caret: number,
  step: 1 | -1,
): Field | null {
  const all = fields(text);
  if (all.length === 0) return null;

  if (step === 1) {
    // Строго правее курсора: иначе Tab внутри поля никуда не уводит.
    const found = all.find((f) => f.start > caret);
    return found ?? null;
  }
  const before = all.filter((f) => f.end < caret);
  return before.length > 0 ? before[before.length - 1] : null;
}

/**
 * Вставить шаблон, заменив выделение.
 *
 * Возвращает новый текст и поле, в которое ставить курсор: первую дырку
 * шаблона, а если дырок нет (например, вставили «\pi») — место сразу за
 * вставленным.
 */
/**
 * Добавить строку в систему или матрицу — после ТЕКУЩЕЙ строки.
 *
 * Обычная вставка «по курсору» здесь даёт мусор: курсор стоит внутри
 * поля, и `\\ {▯}` уезжает в середину уравнения — `{ \\ {▯}3=z}`
 * вместо новой строки. Поэтому точка вставки не там, где каретка, а
 * сразу за концом поля, в котором она стоит.
 *
 * Курсора нет ни в каком поле (например, он в самом конце строки) —
 * вставляем перед `\end{…}`, если оно есть, иначе просто по месту.
 */
export function insertRow(
  text: string,
  caret: number,
  row: string,
): { text: string; select: Field } {
  const all = fields(text);
  const current = all.find((f) => caret >= f.start && caret <= f.end);

  if (current) {
    // За закрывающей скобкой поля: `{y=2}` → сразу после `}`.
    const at = text[current.end] === "}" ? current.end + 1 : current.end;
    return insert(text, at, at, row);
  }

  const end = text.lastIndexOf("\\end{");
  if (end < 0) return insert(text, caret, caret, row);

  // Перед `\end`, приведя пробелы перед ним к одному: иначе выходит
  // «{y=2}␣␣\\ {▯}\end{cases}» — с двойным пробелом и без пробела перед
  // `\end`. Рисуется одинаково, но читать и править потом человеку.
  //
  // Точка вставки схлопнута намеренно: `insert` заворачивает выделенное
  // в первую дырку, и вставка «поверх пробелов» затолкала бы в дырку
  // пробел вместо того, чтобы оставить её пустой.
  let from = end;
  while (from > 0 && /\s/.test(text[from - 1])) from--;
  return insert(text.slice(0, from) + " " + text.slice(end), from, from, row);
}

export function insert(
  text: string,
  selectionStart: number,
  selectionEnd: number,
  template: string,
): { text: string; select: Field } {
  // Выделенное не выбрасывается, а уезжает в первую дырку: «взял 2+2,
  // нажал корень» обязано дать корень из 2+2, а не пустой корень.
  const taken = text.slice(selectionStart, selectionEnd);
  let body = template;
  if (taken) {
    const hole = template.indexOf(HOLE);
    if (hole >= 0) {
      body = template.slice(0, hole) + taken + template.slice(hole + 1);
    }
  }
  const next = text.slice(0, selectionStart) + body + text.slice(selectionEnd);

  const holeInBody = body.indexOf(HOLE);
  if (holeInBody >= 0) {
    const at = selectionStart + holeInBody;
    return { text: next, select: { start: at, end: at + 1 } };
  }
  const at = selectionStart + body.length;
  return { text: next, select: { start: at, end: at } };
}
