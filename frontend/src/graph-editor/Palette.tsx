// Палитра узлов — строится ТОЛЬКО из GET /graph/catalog (правило §1.2:
// каталог нигде не хардкодится клиентом). Категории сворачиваемые, поиск
// по подстроке; клик добавляет узел в текущий подграф.

import { useMemo, useState } from "react";
import type { Catalog, CatalogNode } from "./types";
import { typeHasTaskOutput } from "./model";
import { useEditor } from "./store";
import styles from "../styles/graph-editor.module.css";

// Русские подписи категорий — как в палитре десктопа.
const CATEGORY_LABELS: Record<string, string> = {
  source: "Источники",
  compute: "Вычисление",
  control: "Управление",
  list: "Списки",
  content: "Блоки контента",
  assembly: "Сборка задания",
  task: "Задание",
  symbolic: "Символьные",
  linalg: "Линейная алгебра",
  ode: "Дифуравнения",
  english: "Английский",
  image: "Изображения",
  plot: "Графика",
};

interface Props {
  catalog: Catalog;
}

export default function Palette({ catalog }: Props) {
  const { state, dispatch, current } = useEditor();
  const [filter, setFilter] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const inSubgraph = state.path.length > 0;

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const byCat = new Map<string, CatalogNode[]>();
    for (const n of catalog.nodes) {
      if (
        q &&
        !n.type_id.toLowerCase().includes(q) &&
        !n.display_name.toLowerCase().includes(q)
      ) {
        continue;
      }
      if (!byCat.has(n.category)) byCat.set(n.category, []);
      byCat.get(n.category)!.push(n);
    }
    return [...byCat.entries()];
  }, [catalog, filter]);

  function defaultParams(n: CatalogNode): Record<string, unknown> {
    const params: Record<string, unknown> = {};
    for (const [key, schema] of Object.entries(n.params_schema)) {
      if (schema.default !== undefined && !schema.optional) {
        params[key] = structuredClone(schema.default);
      }
    }
    return params;
  }

  function addNode(n: CatalogNode) {
    // Инвариант языка: узлы-задания (выход TASK) в подграфах запрещены.
    if (inSubgraph && typeHasTaskOutput(catalog, n.type_id)) return;
    // Каскад позиций, чтобы новые узлы не ложились друг на друга.
    const count = current.nodes.length;
    dispatch({
      kind: "add_node",
      typeId: n.type_id,
      params: defaultParams(n),
      x: 60 + (count % 5) * 48,
      y: 60 + (count % 7) * 42,
    });
  }

  function toggle(cat: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

  return (
    <div className={styles.palette}>
      <input
        className={styles.paletteSearch}
        placeholder="Поиск узла…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <div className={styles.paletteList}>
        {groups.map(([cat, nodes]) => (
          <div key={cat}>
            <button className={styles.paletteCat} onClick={() => toggle(cat)}>
              {collapsed.has(cat) ? "▸" : "▾"} {CATEGORY_LABELS[cat] ?? cat}
              <span className={styles.paletteCount}>{nodes.length}</span>
            </button>
            {!collapsed.has(cat) &&
              nodes.map((n) => {
                const forbidden = inSubgraph && typeHasTaskOutput(catalog, n.type_id);
                return (
                  <button
                    key={n.type_id}
                    className={styles.paletteItem}
                    disabled={forbidden}
                    title={
                      forbidden
                        ? "Узлы-задания запрещены внутри тел циклов"
                        : n.description
                    }
                    onClick={() => addNode(n)}
                  >
                    {n.display_name || n.type_id}
                  </button>
                );
              })}
          </div>
        ))}
      </div>
    </div>
  );
}
