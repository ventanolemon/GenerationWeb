import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { useSession } from "../session";
import type {
  AnalyticsOverview,
  GroupStat,
  StudentStat,
  TaskStat,
} from "../api/types";
import { useAsync } from "../screens/useAsync";
import SortableTable, { type Column } from "../screens/SortableTable";
import { Histogram, Timeseries } from "../screens/charts";
import {
  DIFFICULTY_PILL,
  RU_DIFFICULTY,
  RU_STATUS,
  RU_TASK_TYPE,
  STATUS_PILL,
  num,
  pct,
  signedPp,
  signedPct,
} from "../screens/format";
import styles from "../styles/screens.module.css";

const RANGES = [7, 30, 90] as const;
const DIFF_ORDER = { easy: 0, medium: 1, hard: 2 } as const;
const STATUS_ORDER = { struggling: 0, steady: 1, strong: 2 } as const;

export default function AnalyticsPage() {
  const { identity } = useSession();
  const [rangeDays, setRangeDays] = useState<number>(30);
  const [group, setGroup] = useState<string>(""); // "" = все группы
  // Опции выпадашки берём из НЕфильтрованной загрузки, чтобы выбор одной
  // группы не схлопывал список.
  const [groupOptions, setGroupOptions] = useState<string[]>([]);

  const { data, error, loading } = useAsync<AnalyticsOverview>(
    () => api.analyticsOverview(identity!, { rangeDays, group: group || null }),
    [identity, rangeDays, group],
  );

  useEffect(() => {
    if (data && !group) {
      setGroupOptions(data.groups.map((g) => g.group));
    }
  }, [data, group]);

  const generatedTime = data?.generated_at
    ? new Date(data.generated_at).toLocaleTimeString("ru-RU", {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";
  const scopeLabel =
    data?.scope.role === "admin" ? "все предметы" : "свои и системные предметы";

  return (
    <div className={styles.page}>
      <div className={styles.pageHead}>
        <div>
          <h1 className={styles.h1}>Аналитика успеваемости</h1>
          <p className={styles.sub}>
            Скоуп: {scopeLabel}
            {generatedTime && ` · данные на ${generatedTime}`}
          </p>
        </div>
        <div className={styles.controls}>
          <div className={styles.seg} role="group" aria-label="Период">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                aria-pressed={rangeDays === r}
                onClick={() => setRangeDays(r)}
              >
                {r} дней
              </button>
            ))}
          </div>
          <select
            className={styles.input}
            value={group}
            onChange={(e) => setGroup(e.target.value)}
            aria-label="Группа"
          >
            <option value="">Все группы</option>
            {groupOptions.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className={styles.error}>Не удалось загрузить аналитику: {error}</div>}
      {loading && !data && <div className={styles.state}>Загрузка…</div>}

      {data && data.totals.attempts === 0 ? (
        <div className={styles.state}>
          <div className={styles.stateBig}>Пока нет данных за этот период</div>
          <div>Смените диапазон или дождитесь активности студентов.</div>
        </div>
      ) : (
        data && (
          <>
            <div className={styles.kpiRow}>
              <Kpi value={num(data.totals.attempts)} label="Попыток" delta={data.totals.attempts_delta_pct} kind="pct" />
              <Kpi value={num(data.totals.students_active)} label="Активных студентов" />
              <Kpi value={pct(data.totals.correct_rate)} label="Доля верных" delta={data.totals.correct_rate_delta} kind="pp" />
              <Kpi value={num(data.totals.tasks_active)} label="Активных заданий" />
            </div>

            <div className={styles.grid2}>
              <div className={styles.card}>
                <p className={styles.cardTitle}>Динамика по дням</p>
                <div className={styles.chartWrap}>
                  <Timeseries series={data.timeseries} />
                </div>
                <div className={styles.legend}>
                  <span>
                    <i className={styles.dotCorrect} />
                    верные ответы
                  </span>
                  <span>
                    <i className={styles.dotTrack} />
                    все попытки
                  </span>
                </div>
              </div>
              <div className={styles.card}>
                <p className={styles.cardTitle}>Студенты по доле верных</p>
                <div className={styles.chartWrap}>
                  <Histogram dist={data.correctness_distribution} />
                </div>
              </div>
            </div>

            <TableCard title="Задания" hint="клик по заголовку — сортировка">
              <SortableTable<TaskStat>
                rows={data.tasks}
                rowKey={(t) => t.partition_id}
                initialSort="attempts"
                columns={taskColumns}
              />
            </TableCard>

            <TableCard title="Студенты">
              <SortableTable<StudentStat>
                rows={data.students}
                rowKey={(s) => s.login}
                initialSort="attempts"
                columns={studentColumns}
              />
            </TableCard>

            <TableCard title="Группы">
              <SortableTable<GroupStat>
                rows={data.groups}
                rowKey={(g) => g.group}
                initialSort="attempts"
                columns={groupColumns}
              />
            </TableCard>
          </>
        )
      )}
    </div>
  );
}

function Kpi({
  value,
  label,
  delta,
  kind,
}: {
  value: string;
  label: string;
  delta?: number | null;
  kind?: "pct" | "pp";
}) {
  const hasDelta = delta !== undefined;
  const dir = delta == null ? "flat" : delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const text = kind === "pp" ? signedPp(delta ?? null) : signedPct(delta ?? null);
  return (
    <div className={styles.kpi}>
      <div className={styles.kpiVal}>{value}</div>
      <div className={styles.kpiLabel}>{label}</div>
      {hasDelta && (
        <div className={`${styles.kpiDelta} ${styles[dir]}`}>
          {dir === "up" ? "▲" : dir === "down" ? "▼" : "•"} {text} к пред. периоду
        </div>
      )}
    </div>
  );
}

function TableCard({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className={styles.tableCard}>
      <div className={styles.tableTop}>
        <h3>{title}</h3>
        {hint && <span className={styles.tableHint}>{hint}</span>}
      </div>
      {children}
    </div>
  );
}

// ---------- Колонки таблиц ----------

const taskColumns: Column<TaskStat>[] = [
  {
    key: "name",
    label: "Задание",
    render: (t) => (
      <div className={styles.who}>
        <b>{t.name}</b>
        <span className={styles.mono}>{t.subject}</span>
      </div>
    ),
  },
  {
    key: "type",
    label: "Тип",
    render: (t) => <span className={`${styles.chip} ${styles.type}`}>{RU_TASK_TYPE[t.type]}</span>,
  },
  { key: "attempts", label: "Попыток", num: true },
  {
    key: "correct_rate",
    label: "Верно",
    num: true,
    render: (t) => pct(t.correct_rate),
  },
  {
    key: "avg_attempts_to_correct",
    label: "Ср. попыток",
    num: true,
    sortValue: (t) => t.avg_attempts_to_correct ?? 0,
    render: (t) => (t.avg_attempts_to_correct == null ? "—" : t.avg_attempts_to_correct.toFixed(1)),
  },
  { key: "students", label: "Студентов", num: true },
  {
    key: "difficulty",
    label: "Сложность",
    sortValue: (t) => DIFF_ORDER[t.difficulty],
    render: (t) => (
      <span className={`${styles.pill} ${styles[DIFFICULTY_PILL[t.difficulty]]}`}>
        {RU_DIFFICULTY[t.difficulty]}
      </span>
    ),
  },
];

const studentColumns: Column<StudentStat>[] = [
  {
    key: "fio",
    label: "Студент",
    render: (s) => (
      <div className={styles.who}>
        <b>{s.fio || s.login}</b>
        <span className={styles.mono}>{s.login}</span>
      </div>
    ),
  },
  { key: "group", label: "Группа", render: (s) => s.group || "—" },
  { key: "attempts", label: "Попыток", num: true },
  { key: "correct_rate", label: "Верно", num: true, render: (s) => pct(s.correct_rate) },
  {
    key: "status",
    label: "Статус",
    sortValue: (s) => STATUS_ORDER[s.status],
    render: (s) => (
      <span className={`${styles.pill} ${styles[STATUS_PILL[s.status]]}`}>{RU_STATUS[s.status]}</span>
    ),
  },
];

const groupColumns: Column<GroupStat>[] = [
  { key: "group", label: "Группа", render: (g) => <b>{g.group}</b> },
  { key: "students", label: "Студентов", num: true },
  { key: "attempts", label: "Попыток", num: true },
  { key: "correct_rate", label: "Верно", num: true, render: (g) => pct(g.correct_rate) },
  {
    key: "coverage",
    label: "Охват",
    num: true,
    render: (g) => (
      <div className={styles.solvedCell} style={{ justifyContent: "flex-end" }}>
        <span className={styles.lbl}>{pct(g.coverage)}</span>
        <span className={styles.meter} style={{ maxWidth: 120 }}>
          <i style={{ width: `${Math.round(g.coverage * 100)}%` }} />
        </span>
      </div>
    ),
  },
];
