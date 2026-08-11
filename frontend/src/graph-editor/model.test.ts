// Ветки «условие»/«ответ» и подписи проводов — то, чего просили в
// july_language_wishlist (§7, §8) и чего в редакторе не было.
//
// Проверяется здесь ровно одно свойство и его следствия: ветка узла
// ВЫЧИСЛЯЕТСЯ по графу, а не хранится. Поэтому тесты строят граф и
// спрашивают, кто куда попал, — если бы ветка была авторской пометкой,
// проверять было бы нечего.

import { describe, expect, it } from "vitest";
import {
  addEdge,
  branchMap,
  edgeNote,
  edgeNotesOf,
  emptyGraph,
  pruneInvalidEdges,
  removeEdge,
  removeNode,
  setEdgeNote,
} from "./model";
import type { Catalog, GraphEdgeJson, GraphSpecJson } from "./types";

// Каталог тут нужен только затем, чтобы у узлов были порты: правила
// динамических портов `task` model.ts знает сам.
const CATALOG: Catalog = {
  catalog_version: "test",
  port_types: [],
  conversions: [],
  nodes: [
    {
      type_id: "task",
      category: "assembly",
      display_name: "Задание",
      description: "",
      inputs: [],
      outputs: [{ name: "out", type: "task", required: false }],
      params_schema: {},
    },
    {
      type_id: "static_task",
      category: "assembly",
      display_name: "Задание из блоков",
      description: "",
      inputs: [
        { name: "statement", type: "block_list", required: true },
        { name: "answer", type: "block_list", required: true },
      ],
      outputs: [{ name: "out", type: "task", required: false }],
      params_schema: {},
    },
    {
      type_id: "number",
      category: "sources",
      display_name: "Число",
      description: "",
      inputs: [],
      outputs: [{ name: "out", type: "number", required: false }],
      params_schema: {},
    },
    {
      type_id: "expr_binop",
      category: "compute",
      display_name: "Операция",
      description: "",
      inputs: [],
      outputs: [{ name: "out", type: "number", required: false }],
      params_schema: {},
    },
  ],
};

function graph(
  nodes: { id: string; type: string; params?: Record<string, unknown> }[],
  edges: [string, string][],
): GraphSpecJson {
  return {
    version: 1,
    nodes,
    edges: edges.map(([from, to]) => ({ from, to })),
    meta: { layout: {} },
  };
}

/**
 * Граф: две величины идут в условие, третья — в ответ, четвёртая — в оба.
 *
 *   a → #a# (условие)      c → слот x (ответ)
 *   shared → #s# и слот y  (оба)      dead → никуда
 */
function sample(): GraphSpecJson {
  return graph(
    [
      { id: "a", type: "number" },
      { id: "c", type: "number" },
      { id: "shared", type: "number" },
      { id: "dead", type: "number" },
      {
        id: "fin",
        type: "task",
        params: {
          statement: "Дано #a# и #s#",
          slots: ["x:number", "y:number"],
        },
      },
    ],
    [
      ["a:out", "fin:a"],
      ["c:out", "fin:x"],
      ["shared:out", "fin:s"],
      ["shared:out", "fin:y"],
    ],
  );
}

describe("ветки условия и ответа", () => {
  it("СЧИТАЮТСЯ ПО ГРАФУ, а не хранятся в meta", () => {
    // Главное свойство: ничего не размечали — а деление есть.
    const b = branchMap(CATALOG, sample());
    expect(b.sink).toBe("fin");
    expect(b.nodes.get("a")).toBe("statement");
    expect(b.nodes.get("c")).toBe("answer");
  });

  it("узел, питающий обе стороны, помечен общим", () => {
    // Самый частый случай: величина показана в условии и она же —
    // часть ответа. Отнести её к одной стороне значило бы соврать.
    const b = branchMap(CATALOG, sample());
    expect(b.nodes.get("shared")).toBe("both");
  });

  it("узел, не доходящий до финала, ветки не получает", () => {
    // Отсутствие ветки — это и есть сообщение «ни на что не влияет»;
    // холст красит такие узлы отдельно.
    const b = branchMap(CATALOG, sample());
    expect(b.nodes.has("dead")).toBe(false);
  });

  it("ветку получает провод, а не только узел", () => {
    // У общей величины два провода — и они уходят в РАЗНЫЕ стороны.
    // Красить по узлу-источнику значило бы показать оба одинаковыми.
    const b = branchMap(CATALOG, sample());
    expect(b.edges.get("shared:out->fin:s")).toBe("statement");
    expect(b.edges.get("shared:out->fin:y")).toBe("answer");
  });

  it("ветка тянется вглубь по цепочке, а не только на соседа финала", () => {
    const g = graph(
      [
        { id: "n1", type: "number" },
        { id: "op", type: "expr_binop" },
        { id: "fin", type: "task", params: { slots: ["x:number"] } },
      ],
      [["n1:out", "op:in0"], ["op:out", "fin:x"]],
    );
    const b = branchMap(CATALOG, g);
    expect(b.nodes.get("op")).toBe("answer");
    expect(b.nodes.get("n1")).toBe("answer");
  });

  it("общая ветка распространяется вверх по цепочке", () => {
    // Ромб: одна величина через промежуточный узел уходит и в условие,
    // и в ответ. Предок обязан стать общим, иначе подсветка покажет
    // «эта часть только для ответа» там, где она и в условии тоже.
    const g = graph(
      [
        { id: "root", type: "number" },
        { id: "mid", type: "expr_binop" },
        {
          id: "fin",
          type: "task",
          params: { statement: "Дано #s#", slots: ["x:number"] },
        },
      ],
      [["root:out", "mid:in0"], ["mid:out", "fin:s"], ["mid:out", "fin:x"]],
    );
    const b = branchMap(CATALOG, g);
    expect(b.nodes.get("mid")).toBe("both");
    expect(b.nodes.get("root")).toBe("both");
  });

  it("маркер шаблона ответа относится к ответу, а не к условию", () => {
    // Тонкость `task`: вход появляется от #имя# и в условии, и в
    // шаблоне ответа. По имени порта их не различить — только по тому,
    // в каком из двух текстов маркер стоит.
    const g = graph(
      [
        { id: "v", type: "number" },
        {
          id: "fin",
          type: "task",
          params: {
            statement: "Посчитайте",
            slots: ["x:number"],
            layout: "template",
            answer_template: "x = #v#",
          },
        },
      ],
      [["v:out", "fin:v"]],
    );
    expect(branchMap(CATALOG, g).nodes.get("v")).toBe("answer");
  });

  it("static_task делится по своим двум портам", () => {
    const g = graph(
      [
        { id: "s", type: "number" },
        { id: "a", type: "number" },
        { id: "fin", type: "static_task" },
      ],
      [["s:out", "fin:statement"], ["a:out", "fin:answer"]],
    );
    const b = branchMap(CATALOG, g);
    expect(b.nodes.get("s")).toBe("statement");
    expect(b.nodes.get("a")).toBe("answer");
  });

  it("без финала веток нет, и это сказано отдельно", () => {
    const g = graph([{ id: "a", type: "number" }], []);
    const b = branchMap(CATALOG, g);
    expect(b.sink).toBeNull();
    expect(b.nodes.size).toBe(0);
  });

  it("при двух финалах ветки не считаются", () => {
    // Граф уже ошибочен; подсветка от произвольно выбранного финала
    // накрыла бы настоящую проблему правдоподобной картинкой.
    const g = graph(
      [
        { id: "f1", type: "static_task" },
        { id: "f2", type: "static_task" },
      ],
      [],
    );
    expect(branchMap(CATALOG, g).sink).toBeNull();
  });
});

describe("подписи проводов", () => {
  const EDGE: GraphEdgeJson = { from: "a:out", to: "fin:x" };

  function wired(): GraphSpecJson {
    return graph(
      [
        { id: "a", type: "number" },
        { id: "fin", type: "task", params: { slots: ["x:number"] } },
      ],
      [["a:out", "fin:x"]],
    );
  }

  it("живут в meta и не трогают ни узлы, ни рёбра", () => {
    const g = setEdgeNote(wired(), EDGE, "уже отсортировано");
    expect(edgeNote(g, EDGE)).toBe("уже отсортировано");
    expect(g.nodes).toEqual(wired().nodes);
    expect(g.edges).toEqual(wired().edges);
  });

  it("пустая подпись стирается, а не хранится пустой строкой", () => {
    const g = setEdgeNote(setEdgeNote(wired(), EDGE, "текст"), EDGE, "   ");
    expect(edgeNotesOf(g)).toEqual({});
  });

  it("подпись уходит вместе со своим проводом", () => {
    // Иначе она пережила бы удаление и всплыла на новом проводе между
    // теми же портами — с текстом, написанным про другое.
    const g = removeEdge(setEdgeNote(wired(), EDGE, "текст"), EDGE);
    expect(edgeNotesOf(g)).toEqual({});
  });

  it("подпись уходит вместе с удалённым узлом", () => {
    const g = removeNode(setEdgeNote(wired(), EDGE, "текст"), "a");
    expect(edgeNotesOf(g)).toEqual({});
  });

  it("вытесненный провод уносит свою подпись", () => {
    // На один вход провод один: новый вытесняет старый. Подпись была
    // написана про старый.
    let g = setEdgeNote(wired(), EDGE, "текст");
    g = { ...g, nodes: [...g.nodes, { id: "b", type: "number" }] };
    g = addEdge(g, "b:out", "fin:x");
    expect(edgeNotesOf(g)).toEqual({});
  });

  it("подпись переживает правку, не затронувшую её провод", () => {
    let g = setEdgeNote(wired(), EDGE, "текст");
    g = { ...g, nodes: [...g.nodes, { id: "b", type: "number" }] };
    g = removeNode(g, "b");
    expect(edgeNote(g, EDGE)).toBe("текст");
  });

  it("обрезка рёбер по портам уносит и подписи", () => {
    const g = pruneInvalidEdges(
      setEdgeNote(
        graph(
          [
            { id: "a", type: "number" },
            // Слот пропал — вместе с ним пропадает вход fin:x.
            { id: "fin", type: "task", params: { slots: [] } },
          ],
          [["a:out", "fin:x"]],
        ),
        EDGE,
        "текст",
      ),
      CATALOG,
    );
    expect(g.edges).toEqual([]);
    expect(edgeNotesOf(g)).toEqual({});
  });

  it("у пустого графа подписей нет", () => {
    expect(edgeNotesOf(emptyGraph())).toEqual({});
  });
});
