import { describe, expect, it } from "vitest";
import { HOLE, fields, hasHoles, insert, insertRow, nextField } from "./fields";
import { ADD_ROW, TEMPLATES } from "./templates";

const at = (text: string, f: { start: number; end: number }) =>
  text.slice(f.start, f.end);

describe("поля формулы", () => {
  it("находит дырки шаблона", () => {
    const text = `\\frac{${HOLE}}{${HOLE}}`;
    expect(fields(text).map((f) => at(text, f))).toEqual([HOLE, HOLE]);
  });

  it("ПОЛЕ ОСТАЁТСЯ ПОЛЕМ ПОСЛЕ ЗАПОЛНЕНИЯ", () => {
    // Главное требование: вернуться в числитель и поправить его, а не
    // стирать дробь целиком. Дырка исчезает с первым символом, скобки —
    // нет, и поле опознаётся по ним.
    const text = "\\frac{2x}{3}";
    expect(fields(text).map((f) => at(text, f))).toEqual(["2x", "3"]);
  });

  it("не считает полем имя окружения", () => {
    const text = `\\begin{cases} {${HOLE}} \\\\ {${HOLE}} \\end{cases}`;
    expect(fields(text).map((f) => at(text, f))).toEqual([HOLE, HOLE]);
  });

  it("не считает полем имя окружения и после заполнения", () => {
    const text = "\\begin{cases} {x = 1} \\\\ {y = 2} \\end{cases}";
    expect(fields(text).map((f) => at(text, f))).toEqual(["x = 1", "y = 2"]);
  });

  it("берёт листовые группы, а не обёртки", () => {
    const text = "\\frac{\\sqrt{2}}{3}";
    expect(fields(text).map((f) => at(text, f))).toEqual(["2", "3"]);
  });

  it("не путает экранированную скобку с группой", () => {
    const text = "\\left\\{{x}\\right.";
    expect(fields(text).map((f) => at(text, f))).toEqual(["x"]);
  });

  it("видит дырку без скобок", () => {
    expect(fields(`x + ${HOLE}`).length).toBe(1);
  });

  it("у пустой строки полей нет", () => {
    expect(fields("")).toEqual([]);
    expect(fields("2 + 2")).toEqual([]);
  });
});

describe("переход между полями", () => {
  const text = `\\frac{${HOLE}}{${HOLE}}`;

  it("Tab идёт вперёд", () => {
    const first = nextField(text, 0, 1)!;
    expect(at(text, first)).toBe(HOLE);
    const second = nextField(text, first.end, 1)!;
    expect(second.start).toBeGreaterThan(first.start);
  });

  it("Shift+Tab идёт назад", () => {
    const all = fields(text);
    const back = nextField(text, all[1].start, -1)!;
    expect(back.start).toBe(all[0].start);
  });

  it("с последнего поля вперёд уводить некуда", () => {
    const all = fields(text);
    expect(nextField(text, all[all.length - 1].end, 1)).toBeNull();
  });

  it("с первого поля назад уводить некуда", () => {
    expect(nextField(text, 0, -1)).toBeNull();
  });

  it("возвращает в заполненное поле", () => {
    const filled = "\\frac{2x}{3}";
    const back = nextField(filled, filled.length, -1)!;
    expect(at(filled, back)).toBe("3");
    const earlier = nextField(filled, back.start - 1, -1)!;
    expect(at(filled, earlier)).toBe("2x");
  });
});

describe("вставка шаблона", () => {
  it("ставит курсор в первую дырку", () => {
    const r = insert("", 0, 0, `\\frac{${HOLE}}{${HOLE}}`);
    expect(r.text).toBe(`\\frac{${HOLE}}{${HOLE}}`);
    expect(at(r.text, r.select)).toBe(HOLE);
    expect(r.select.start).toBe(6);
  });

  it("заворачивает выделенное в первую дырку", () => {
    // «Выделил 2+2, нажал корень» обязано дать корень ИЗ 2+2.
    const text = "2+2";
    const r = insert(text, 0, 3, `\\sqrt{${HOLE}}`);
    expect(r.text).toBe("\\sqrt{2+2}");
  });

  it("вставляет в середину, не портя соседей", () => {
    const r = insert("a+b", 2, 2, `\\sqrt{${HOLE}}`);
    expect(r.text).toBe(`a+\\sqrt{${HOLE}}b`);
  });

  it("без дырок ставит курсор за вставленным", () => {
    const r = insert("", 0, 0, "\\pi");
    expect(r.select).toEqual({ start: 3, end: 3 });
  });
});

describe("шаблоны палитры", () => {
  it("каждая дырка обёрнута своей парой скобок", () => {
    // Иначе поле не переживёт заполнение — см. главный тест выше.
    for (const t of [...TEMPLATES, ADD_ROW]) {
      const filled = t.latex.split(HOLE).join("z");
      const found = fields(filled).length;
      const holes = t.latex.split(HOLE).length - 1;
      expect(found, `${t.title}: полей ${found}, дырок ${holes}`).toBe(holes);
    }
  });

  it("в каждом шаблоне есть хотя бы одна дырка", () => {
    for (const t of [...TEMPLATES, ADD_ROW]) {
      expect(hasHoles(t.latex), t.title).toBe(true);
    }
  });

  it("система и матрица дают по нескольку полей", () => {
    const cases = TEMPLATES.find((t) => t.title === "Система")!;
    expect(fields(cases.latex).length).toBe(2);
    const matrix = TEMPLATES.find((t) => t.title === "Матрица 2×2")!;
    expect(fields(matrix.latex).length).toBe(4);
  });

  it("добавленная строка системы — тоже поле", () => {
    const cases = TEMPLATES.find((t) => t.title === "Система")!;
    const filled = cases.latex.split(HOLE).join("z");
    const grown = insertRow(filled, filled.length, ADD_ROW.latex);
    expect(fields(grown.text).length).toBe(3);
  });
});

describe("незаполненные места", () => {
  it("видны, пока дырка на месте", () => {
    expect(hasHoles(`\\frac{${HOLE}}{2}`)).toBe(true);
    expect(hasHoles("\\frac{1}{2}")).toBe(false);
  });
});


describe("новая строка системы", () => {
  const CASES = "\\begin{cases} {x=1} \\\\ {y=2} \\end{cases}";

  it("встаёт ПОСЛЕ строки, в которой курсор, а не по каретке", () => {
    // Курсор стоит внутри поля, и вставка «по месту» уезжала в середину
    // уравнения: `{ \\ {▯}3=z}` вместо новой строки. Проверено в
    // браузере — там это и вылезло.
    const inside = CASES.indexOf("y=2") + 1;
    const grown = insertRow(CASES, inside, ` \\\\ {${HOLE}}`);
    expect(grown.text).toBe(
      `\\begin{cases} {x=1} \\\\ {y=2} \\\\ {${HOLE}} \\end{cases}`);
  });

  it("после первой строки — тоже после неё, а не в конец", () => {
    const inside = CASES.indexOf("x=1") + 1;
    const grown = insertRow(CASES, inside, ` \\\\ {${HOLE}}`);
    expect(grown.text).toBe(
      `\\begin{cases} {x=1} \\\\ {${HOLE}} \\\\ {y=2} \\end{cases}`);
  });

  it("курсор не в поле — перед \\end", () => {
    const grown = insertRow(CASES, CASES.length, ` \\\\ {${HOLE}}`);
    expect(grown.text).toContain(`{y=2} \\\\ {${HOLE}} \\end{cases}`);
  });

  it("курсор ставится в новую дырку", () => {
    const grown = insertRow(CASES, CASES.length, ` \\\\ {${HOLE}}`);
    expect(grown.text.slice(grown.select.start, grown.select.end)).toBe(HOLE);
  });

  it("растит матрицу так же", () => {
    const m = `\\begin{pmatrix} {1} & {2} \\\\ {3} & {4} \\end{pmatrix}`;
    const grown = insertRow(m, m.indexOf("4") + 1, ` \\\\ {${HOLE}}`);
    expect(grown.text).toContain(`{4} \\\\ {${HOLE}} \\end{pmatrix}`);
  });
});
