import { beforeEach, describe, expect, it } from "vitest";
import {
  answer, canConnect, connect, disconnect, formula, inputs, layout, newGate,
  output, problems, remove, resetIds, unused,
} from "./model";

const VARS = ["A", "B", "C"];

/** Схема `not(A) v (B ^ C)` — та же, что в примерах ядра. */
function sample() {
  const not = newGate("NOT");
  const and = newGate("AND");
  const or = newGate("OR");
  let nodes = [...inputs(VARS), not, and, or];
  nodes = connect(nodes, "in:A", not.id, 0);
  nodes = connect(nodes, "in:B", and.id, 0);
  nodes = connect(nodes, "in:C", and.id, 1);
  nodes = connect(nodes, not.id, or.id, 0);
  nodes = connect(nodes, and.id, or.id, 1);
  return { nodes, not, and, or };
}

beforeEach(() => resetIds());

describe("формула собранной схемы", () => {
  it("ЗАПИСЫВАЕТСЯ ТАК ЖЕ, КАК ЕЁ ПИШУТ РУКОЙ", () => {
    // Главное свойство холста: он отвечает тем же, что студент написал
    // бы сам. Поэтому проверять его нечем особенным — ядро уже умеет.
    const { nodes } = sample();
    expect(answer(nodes)).toBe("(not(A) v (B ^ C))");
  });

  it("вход сам по себе — это его имя", () => {
    const nodes = inputs(VARS);
    expect(formula(nodes, "in:B")).toBe("B");
  });

  it("пустая схема ответа не даёт", () => {
    expect(answer(inputs(VARS))).toBe("");
  });

  it("незаконченная схема ответа не даёт", () => {
    const gate = newGate("AND");
    const nodes = connect([...inputs(VARS), gate], "in:A", gate.id, 0);
    expect(output(nodes)).not.toBeNull();
    expect(problems(nodes, VARS)[0].text).toMatch(/не подключены/);
  });
});

describe("соединения", () => {
  it("петля не допускается", () => {
    const { nodes, and, or } = sample();
    // Выход OR уже питается от AND; обратный провод замкнул бы круг.
    expect(canConnect(nodes, or.id, and.id, 0)).toBe(false);
  });

  it("сам на себя нельзя", () => {
    const { nodes, and } = sample();
    expect(canConnect(nodes, and.id, and.id, 0)).toBe(false);
  });

  it("один источник дважды на один вентиль нельзя", () => {
    // `A & A` рисуется двумя проводами и означает `A` — это не схема, а
    // ошибка чертежа.
    const gate = newGate("AND");
    let nodes = [...inputs(VARS), gate];
    nodes = connect(nodes, "in:A", gate.id, 0);
    expect(canConnect(nodes, "in:A", gate.id, 1)).toBe(false);
  });

  it("во вход схемы провод не втыкается", () => {
    const { nodes, and } = sample();
    expect(canConnect(nodes, and.id, "in:A", 0)).toBe(false);
  });

  it("у НЕ ровно один вход", () => {
    const { nodes, not } = sample();
    expect(canConnect(nodes, "in:B", not.id, 1)).toBe(false);
  });

  it("переподключение заменяет провод, а не добавляет", () => {
    const { nodes, not } = sample();
    const next = connect(nodes, "in:C", not.id, 0);
    expect(formula(next, not.id)).toBe("not(C)");
  });

  it("снятие провода освобождает вход", () => {
    const { nodes, not } = sample();
    const next = disconnect(nodes, not.id, 0);
    expect(problems(next, VARS).some((p) => p.nodeId === not.id)).toBe(true);
  });
});

describe("удаление", () => {
  it("убирает вентиль и провода в него", () => {
    const { nodes, and, or } = sample();
    const next = remove(nodes, and.id);
    expect(next.find((n) => n.id === and.id)).toBeUndefined();
    expect(next.find((n) => n.id === or.id)!.inputs).not.toContain(and.id);
  });
});

describe("что мешает ответить", () => {
  it("готовая схема нареканий не вызывает", () => {
    expect(problems(sample().nodes, VARS)).toEqual([]);
  });

  it("пустая схема названа пустой", () => {
    expect(problems(inputs(VARS), VARS)[0].text).toMatch(/пуста/);
  });

  it("два выхода — это не схема", () => {
    const { nodes, or } = sample();
    const extra = newGate("NOT");
    let next = [...nodes, extra];
    next = connect(next, "in:A", extra.id, 0);
    expect(unused(next).filter((n) => n.type !== "INPUT")).toHaveLength(2);
    expect(problems(next, VARS)[0].text).toMatch(/больше одного выхода/);
    void or;
  });

  it("НЕПОДКЛЮЧЁННЫЙ ВХОД НАЗЫВАЕТСЯ ПОИМЁННО", () => {
    // Тот же дефект, что нашёлся в самом генераторе схем: вход
    // нарисован и ни на что не влияет. Раз это ошибка у генератора, то
    // и у студента тоже.
    const not = newGate("NOT");
    const or = newGate("OR");
    let nodes = [...inputs(VARS), not, or];
    nodes = connect(nodes, "in:A", not.id, 0);
    nodes = connect(nodes, not.id, or.id, 0);
    nodes = connect(nodes, "in:B", or.id, 1);
    const found = problems(nodes, VARS);
    expect(found).toHaveLength(1);
    expect(found[0].text).toContain("C");
  });
});

describe("раскладка", () => {
  it("источник всегда левее потребителя", () => {
    const placed = layout(sample().nodes);
    const at = (id: string) => placed.find((p) => p.node.id === id)!;
    for (const p of placed) {
      for (const child of p.node.inputs) {
        if (child) expect(at(child).x).toBeLessThan(p.x);
      }
    }
  });

  it("каждый узел размещён ровно один раз", () => {
    const { nodes } = sample();
    expect(layout(nodes)).toHaveLength(nodes.length);
  });
});
