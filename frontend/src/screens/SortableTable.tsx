import { useMemo, useState, type ReactNode } from "react";
import styles from "../styles/screens.module.css";

export interface Column<T> {
  key: string;
  label: string;
  /** Правое выравнивание + табличные цифры. */
  num?: boolean;
  /** По умолчанию столбцы сортируемы; false — заголовок не кликается. */
  sortable?: boolean;
  /** Значение для сортировки (по умолчанию (row as any)[key]). */
  sortValue?: (row: T) => number | string;
  /** Рендер ячейки (по умолчанию String((row as any)[key])). */
  render?: (row: T) => ReactNode;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  initialSort: string;
  /** -1 по убыванию (по умолчанию), 1 по возрастанию. */
  initialDir?: 1 | -1;
}

/**
 * Универсальная сортируемая таблица (порт sortableTable из макета). Клик по
 * заголовку меняет ключ/направление; числовые столбцы сортируются как
 * числа, строковые — локале-сравнением по-русски.
 */
export default function SortableTable<T>({
  columns,
  rows,
  rowKey,
  initialSort,
  initialDir = -1,
}: Props<T>) {
  const [sortKey, setSortKey] = useState(initialSort);
  const [sortDir, setSortDir] = useState<1 | -1>(initialDir);

  const valueOf = (col: Column<T>, row: T): number | string =>
    col.sortValue ? col.sortValue(row) : ((row as Record<string, unknown>)[col.key] as number | string);

  const sorted = useMemo(() => {
    const col = columns.find((c) => c.key === sortKey);
    if (!col) return rows;
    return [...rows].sort((a, b) => {
      const va = valueOf(col, a);
      const vb = valueOf(col, b);
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * sortDir;
      return String(va).localeCompare(String(vb), "ru") * sortDir;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sortKey, sortDir, columns]);

  function toggleSort(col: Column<T>) {
    if (col.sortable === false) return;
    if (col.key === sortKey) {
      setSortDir((d) => (d === -1 ? 1 : -1));
    } else {
      setSortKey(col.key);
      setSortDir(-1);
    }
  }

  return (
    <div className={styles.tScroll}>
      <table className={styles.t}>
        <thead>
          <tr>
            {columns.map((col) => {
              const sortable = col.sortable !== false;
              const cls = [col.num ? styles.num : "", sortable ? styles.sortable : ""]
                .filter(Boolean)
                .join(" ");
              return (
                <th
                  key={col.key}
                  className={cls}
                  onClick={() => toggleSort(col)}
                  aria-sort={
                    col.key === sortKey ? (sortDir === -1 ? "descending" : "ascending") : undefined
                  }
                >
                  {col.label}
                  {col.key === sortKey && <span className={styles.arw}>{sortDir === -1 ? "▼" : "▲"}</span>}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((col) => (
                <td key={col.key} className={col.num ? styles.num : undefined}>
                  {col.render
                    ? col.render(row)
                    : String((row as Record<string, unknown>)[col.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
