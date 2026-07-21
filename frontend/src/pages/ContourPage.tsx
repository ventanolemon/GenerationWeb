import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { useSession } from "../session";
import type {
  ContourJobDetail,
  ContourStatus,
  CriticVerdict,
  ProbeRun,
  Subject,
} from "../api/types";
import { useAsync } from "../screens/useAsync";
import { num } from "../screens/format";
import s from "../styles/screens.module.css";
import c from "../styles/contour.module.css";

// ─── Русские подписи / статусные цвета ───────────────────────────────────

const STATUS_RU: Record<ContourStatus, string> = {
  queued: "в очереди",
  generating: "генерация",
  validating: "валидация",
  critic: "критик",
  awaiting_human: "ждёт решения",
  approved: "принято",
  rejected: "отклонено",
  escalated: "эскалация",
  failed: "ошибка",
};
type Pill = "ok" | "warn" | "bad" | "mut";
const STATUS_PILL: Record<ContourStatus, Pill> = {
  queued: "mut",
  generating: "mut",
  validating: "mut",
  critic: "mut",
  awaiting_human: "warn",
  approved: "ok",
  rejected: "bad",
  escalated: "bad",
  failed: "bad",
};
const IN_FLIGHT: ContourStatus[] = ["queued", "generating", "validating", "critic"];

const VERDICT_RU: Record<CriticVerdict["verdict"], string> = {
  accept: "принять",
  revise: "доработать",
  reject: "отклонить",
};
const VERDICT_PILL: Record<CriticVerdict["verdict"], Pill> = {
  accept: "ok",
  revise: "warn",
  reject: "bad",
};

// Стадии петли для степпера (S0–S6).
const STAGES: { key: ContourStatus | "done"; label: string }[] = [
  { key: "generating", label: "Генерация" },
  { key: "validating", label: "Валидация" },
  { key: "critic", label: "Критик" },
  { key: "awaiting_human", label: "Решение" },
];

function fmtTime(epoch: number): string {
  if (!epoch) return "—";
  const d = new Date(epoch * 1000);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// ─── Экран ────────────────────────────────────────────────────────────────

export default function ContourPage() {
  const { identity } = useSession();
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const jobsQ = useAsync(() => api.contourListJobs(identity!), [identity]);
  const jobs = jobsQ.data?.jobs ?? [];

  const subjectsQ = useAsync(() => api.listSubjects(), []);
  const subjectName = useMemo(() => {
    const m = new Map<number, string>();
    (subjectsQ.data ?? []).forEach((sub) => m.set(sub.id, sub.name));
    return (id: number) => m.get(id) ?? `предмет #${id}`;
  }, [subjectsQ.data]);

  // Лёгкий поллинг очереди, пока есть незавершённые джобы.
  useEffect(() => {
    if (!jobs.some((j) => IN_FLIGHT.includes(j.status))) return;
    const t = setInterval(jobsQ.reload, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs]);

  if (selected) {
    return (
      <JobDetail
        jobId={selected}
        subjectName={subjectName}
        onBack={() => setSelected(null)}
        onDecided={() => {
          setSelected(null);
          jobsQ.reload();
        }}
      />
    );
  }

  const awaiting = jobs.filter((j) => j.status === "awaiting_human").length;
  const inflight = jobs.filter((j) => IN_FLIGHT.includes(j.status)).length;
  const approved = jobs.filter((j) => j.status === "approved").length;

  return (
    <div className={s.page}>
      <div className={s.pageHead}>
        <div>
          <h1 className={s.h1}>Контур ИИ-генерации</h1>
          <p className={s.sub}>
            Описание → граф → probe-прогон → критик → ваше решение. Задание попадает
            в предмет только после утверждения человеком.
          </p>
        </div>
        <button className={`${s.btn} ${s.primary}`} onClick={() => setCreating(true)}>
          + Новое задание
        </button>
      </div>

      <div className={s.kpiRow} style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        <Kpi value={num(awaiting)} label="Ждут вашего решения" hint="probe и критик уже отработали" />
        <Kpi value={num(inflight)} label="В работе у контура" hint="очередь · генерация · критик" />
        <Kpi value={num(approved)} label="Принято вами" hint="стали заданиями в предмете" />
      </div>

      {creating && (
        <NewJobForm
          subjects={subjectsQ.data ?? []}
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            jobsQ.reload();
          }}
        />
      )}

      <div className={s.tableCard}>
        <div className={s.tableTop}>
          <h3>Задания контура</h3>
          <span className={s.tableHint}>клик по строке — детальный обзор</span>
        </div>
        {jobsQ.error && <div className={s.error} style={{ margin: 16 }}>{jobsQ.error}</div>}
        {jobsQ.loading && !jobsQ.data && <div className={s.state}>Загрузка…</div>}
        {jobsQ.data && jobs.length === 0 ? (
          <div className={s.state}>
            <div className={s.stateBig}>Заданий пока нет</div>
            <div>Опишите задание кнопкой «+ Новое задание» — контур соберёт и проверит генератор.</div>
          </div>
        ) : (
          jobsQ.data && (
            <div className={s.tScroll}>
              <table className={s.t}>
                <thead>
                  <tr>
                    <th>Задание</th>
                    <th>Предмет</th>
                    <th>Статус</th>
                    <th>Создано</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((j) => (
                    <tr key={j.job_id} style={{ cursor: "pointer" }} onClick={() => setSelected(j.job_id)}>
                      <td><b>{j.description}</b></td>
                      <td>{subjectName(j.subject_id)}</td>
                      <td><StatusPill status={j.status} /></td>
                      <td>{fmtTime(j.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: ContourStatus }) {
  return <span className={`${s.pill} ${s[STATUS_PILL[status]]}`}>{STATUS_RU[status] ?? status}</span>;
}

function Kpi({ value, label, hint }: { value: string; label: string; hint?: string }) {
  return (
    <div className={s.kpi}>
      <div className={s.kpiVal}>{value}</div>
      <div className={s.kpiLabel}>{label}</div>
      {hint && <div className={s.kpiLabel} style={{ color: "var(--text-faint)", marginTop: 6 }}>{hint}</div>}
    </div>
  );
}

// ─── Форма нового задания ─────────────────────────────────────────────────

function NewJobForm({
  subjects,
  onClose,
  onCreated,
}: {
  subjects: Subject[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const { identity } = useSession();
  const [description, setDescription] = useState("");
  const [subjectId, setSubjectId] = useState<number | null>(subjects[0]?.id ?? null);
  const [taskType, setTaskType] = useState<"static" | "interactive">("static");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (subjectId == null && subjects.length) setSubjectId(subjects[0].id);
  }, [subjects, subjectId]);

  async function submit() {
    if (!description.trim() || subjectId == null) return;
    setBusy(true);
    setErr(null);
    try {
      await api.contourCreateJob(identity!, {
        description: description.trim(),
        subject_id: subjectId,
        constraints: { task_type: taskType },
      });
      onCreated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.card} style={{ marginBottom: 16 }}>
      <p className={s.cardTitle}>Новое задание через ИИ</p>
      {err && <div className={s.error}>{err}</div>}
      <textarea
        className={s.input}
        style={{ width: "100%", minHeight: 74, resize: "vertical", marginBottom: 10 }}
        placeholder="Опишите желаемое задание: тема, тип чисел, что найти, ограничения…"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="Предмет">
          <select
            className={s.input}
            value={subjectId ?? ""}
            onChange={(e) => setSubjectId(Number(e.target.value))}
          >
            {subjects.map((sub) => (
              <option key={sub.id} value={sub.id}>{sub.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Тип">
          <div className={s.seg} role="group" aria-label="Тип задания">
            <button type="button" aria-pressed={taskType === "static"} onClick={() => setTaskType("static")}>Статическое</button>
            <button type="button" aria-pressed={taskType === "interactive"} onClick={() => setTaskType("interactive")}>Интерактив</button>
          </div>
        </Field>
        <span style={{ flex: 1 }} />
        <button className={s.btn} onClick={onClose} disabled={busy}>Отмена</button>
        <button
          className={`${s.btn} ${s.primary}`}
          onClick={submit}
          disabled={!description.trim() || subjectId == null || busy}
        >
          {busy ? "Запуск…" : "Запустить контур"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: "var(--text-muted)" }}>
      {label}
      {children}
    </label>
  );
}

// ─── Деталь джобы ─────────────────────────────────────────────────────────

function JobDetail({
  jobId,
  subjectName,
  onBack,
  onDecided,
}: {
  jobId: string;
  subjectName: (id: number) => string;
  onBack: () => void;
  onDecided: () => void;
}) {
  const { identity } = useSession();
  const { data, error, loading, reload } = useAsync<ContourJobDetail>(
    () => api.contourGetJob(identity!, jobId),
    [identity, jobId],
  );
  const [curSeed, setCurSeed] = useState(0);
  const [partName, setPartName] = useState("");
  const [note, setNote] = useState("");
  const [acting, setActing] = useState(false);
  const [actErr, setActErr] = useState<string | null>(null);

  // Поллинг, пока джоба в работе.
  useEffect(() => {
    if (!data || !IN_FLIGHT.includes(data.status)) return;
    const t = setInterval(reload, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.status]);

  if (loading && !data) return <div className={s.page}><div className={s.state}>Загрузка…</div></div>;
  if (error) return <div className={s.page}><button className={c.backLink} onClick={onBack}>← К очереди контура</button><div className={s.error}>{error}</div></div>;
  if (!data) return null;

  const runs = data.probe?.runs ?? [];
  const agg = data.probe?.aggregates;
  const run = runs[Math.min(curSeed, Math.max(runs.length - 1, 0))];
  const canDecide = data.status === "awaiting_human";

  async function decide(kind: "approve" | "reject") {
    setActErr(null);
    if (kind === "reject") {
      const reason = window.prompt("Причина отклонения (уйдёт в лог эскалаций):");
      if (!reason || !reason.trim()) return;
      setActing(true);
      try {
        await api.contourReject(identity!, jobId, reason.trim());
        onDecided();
      } catch (e) {
        setActErr(e instanceof Error ? e.message : String(e));
      } finally {
        setActing(false);
      }
      return;
    }
    setActing(true);
    try {
      const res = await api.contourApprove(identity!, jobId, {
        partition_name: partName.trim(),
        note: note.trim(),
      });
      window.alert(
        res.corpus_deduplicated
          ? `Задание добавлено в предмет (партиция #${res.partition_id}). Корпусная запись — дубль по graph_hash, пропущена.`
          : `Задание добавлено в предмет (партиция #${res.partition_id}) и записано в корпус.`,
      );
      onDecided();
    } catch (e) {
      setActErr(e instanceof Error ? e.message : String(e));
    } finally {
      setActing(false);
    }
  }

  return (
    <div className={s.page}>
      <button className={c.backLink} onClick={onBack}>← К очереди контура</button>
      <div className={s.pageHead}>
        <div>
          <h1 className={s.h1}>{data.description}</h1>
          <p className={s.sub}>
            <StatusPill status={data.status} /> &nbsp; {subjectName(data.subject_id)} · {jobId} · создано {fmtTime(data.created_at)}
          </p>
        </div>
      </div>

      {data.error && <div className={s.error}>Ошибка контура: {data.error}</div>}

      <Stepper status={data.status} />

      {runs.length === 0 ? (
        <div className={s.state}>
          <div className={s.stateBig}>{IN_FLIGHT.includes(data.status) ? "Контур ещё работает" : "Нет probe-отчёта"}</div>
          <div>{IN_FLIGHT.includes(data.status) ? "Обновится автоматически, как воркер соберёт и прогонит граф." : "У этой джобы нет данных прогона."}</div>
        </div>
      ) : (
        <>
          <div className={s.grid2}>
            {/* Превью выбранного seed */}
            <div className={s.card}>
              <p className={s.cardTitle}>Превью задания — probe-прогон</p>
              <div className={c.seedRow}>
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>seed:</span>
                {runs.map((r, i) => (
                  <button
                    key={r.seed}
                    className={c.seedChip}
                    aria-pressed={i === curSeed}
                    onClick={() => setCurSeed(i)}
                    title={`probe seed ${r.seed}`}
                  >
                    {r.seed}
                  </button>
                ))}
              </div>
              {run && <RunPreview run={run} />}
            </div>

            {/* SYM-флаги + агрегаты */}
            <div className={s.card}>
              <p className={s.cardTitle}>SYM-проверки</p>
              {data.flags.length === 0 ? (
                <div className={c.allClear}>✓ Провалов не найдено — все детерминированные проверки чисты.</div>
              ) : (
                data.flags.map((f, i) => (
                  <div className={c.flagRow} key={`${f.code}-${i}`}>
                    <span className={`${c.flagCode} ${f.severity === "block" ? c.flagBlock : c.flagWarn}`}>{f.code}</span>
                    <span className={c.flagDetail}>{f.detail}</span>
                  </div>
                ))
              )}
              {agg && (
                <>
                  <p className={s.cardTitle} style={{ marginTop: 16 }}>Probe-агрегаты</p>
                  <div className={c.aggGrid}>
                    <Agg v={`${agg.distinct_statements}/${agg.runs_ok}`} l="различимых условий" />
                    <Agg v={`${agg.distinct_answers}/${agg.runs_ok}`} l="различимых ответов" />
                    <Agg v={agg.double_run_mismatch ? "✕" : "✓"} l="детерминизм (F2)" />
                    <Agg v={String(agg.attempts_p50)} l="attempts p50" />
                    <Agg v={String(agg.attempts_max)} l="attempts max" />
                    <Agg v={`${Math.round(agg.wall_ms_max)} мс`} l="wall max" />
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Таблица прогонов */}
          <div className={s.tableCard}>
            <div className={s.tableTop}><h3>Прогоны probe — {runs.length} seed</h3></div>
            <div className={s.tScroll}>
              <table className={s.t}>
                <thead>
                  <tr>
                    <th className={s.num}>seed</th>
                    <th>Условие</th>
                    <th>Ответ</th>
                    <th className={s.num}>Попыт.</th>
                    <th className={s.num}>мс</th>
                    <th>Ошибка</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.seed}>
                      <td className={s.num}>{r.seed}</td>
                      <td title={r.statement}>{clip(r.statement, 60)}</td>
                      <td title={r.answer}>{clip(r.answer, 40)}</td>
                      <td className={s.num}>{r.attempts}</td>
                      <td className={s.num}>{Math.round(r.wall_ms)}</td>
                      <td>{r.error ? <span className={`${s.pill} ${s.bad}`}>ошибка</span> : <span className={s.no}>—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* Вердикт критика */}
      {data.critic && (
        <div className={s.card} style={{ marginTop: 16 }}>
          <p className={s.cardTitle}>Вердикт критика</p>
          <div className={c.verdictHead}>
            <span className={`${s.pill} ${s[VERDICT_PILL[data.critic.verdict]]}`}>{VERDICT_RU[data.critic.verdict]}</span>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>уверенность</span>
            <span className={c.confMeter}><i style={{ width: `${Math.round(data.critic.confidence * 100)}%` }} /></span>
            <span style={{ fontVariantNumeric: "tabular-nums", fontSize: 13 }}>{data.critic.confidence.toFixed(2)}</span>
            {data.critic.failures.length === 0 && <span style={{ fontSize: 12, color: "var(--text-faint)" }}>провалов не найдено</span>}
          </div>
          {data.critic.summary && <p className={c.stText}>{data.critic.summary}</p>}
          {data.critic.failures.map((f, i) => (
            <div className={c.flagRow} key={`${f.code}-${i}`}>
              <span className={`${c.flagCode} ${f.severity === "block" ? c.flagBlock : c.flagWarn}`}>{f.code || "—"}</span>
              <span className={c.flagDetail}>{f.detail || f.evidence}{f.detail && f.evidence ? ` — «${f.evidence}»` : ""}</span>
            </div>
          ))}
        </div>
      )}

      {/* Поверхность решения */}
      {canDecide && (
        <>
          {actErr && <div className={s.error} style={{ marginTop: 16 }}>{actErr}</div>}
          <div className={c.decisionBar}>
            <div className={c.decisionInputs}>
              <input
                className={s.input}
                style={{ flex: 1 }}
                placeholder="Имя партиции (пусто — из описания)"
                value={partName}
                onChange={(e) => setPartName(e.target.value)}
              />
              <input
                className={s.input}
                style={{ flex: 1 }}
                placeholder="Заметка к записи корпуса (необязательно)"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>
            <button className={`${s.btn} ${s.danger}`} onClick={() => decide("reject")} disabled={acting}>✕ Отклонить</button>
            <button className={`${s.btn} ${s.primary}`} onClick={() => decide("approve")} disabled={acting}>✓ Утвердить</button>
          </div>
          <p className={c.footNote}>
            Утверждение создаёт задание в предмете (партиция constracted=4) и запись корпуса kind=generate.
            Отклонение уходит в лог эскалаций с вашей причиной.
          </p>
        </>
      )}
    </div>
  );
}

function RunPreview({ run }: { run: ProbeRun }) {
  return (
    <>
      <p className={c.eyebrow}>Условие</p>
      <p className={c.stText}>{run.statement}</p>
      <p className={c.eyebrow}>Ответ</p>
      <div className={c.answerBox}>{run.answer || "—"}</div>
      <div className={c.runMeta}>
        <span>attempts: {run.attempts}</span>
        <span>wall: {Math.round(run.wall_ms)} мс</span>
        <span>error: {run.error ?? "null"}</span>
      </div>
    </>
  );
}

function Agg({ v, l }: { v: string; l: string }) {
  return (
    <div>
      <div className={c.aggVal}>{v}</div>
      <div className={c.aggLabel}>{l}</div>
    </div>
  );
}

function Stepper({ status }: { status: ContourStatus }) {
  // Индекс текущей стадии в конвейере; терминальные — всё пройдено.
  const order: ContourStatus[] = ["queued", "generating", "validating", "critic", "awaiting_human"];
  const terminal = ["approved", "rejected", "escalated", "failed"].includes(status);
  const curIdx = terminal ? STAGES.length : Math.max(0, order.indexOf(status) - 1);
  return (
    <div className={c.stepper}>
      {STAGES.map((st, i) => {
        const done = i < curIdx || terminal;
        const active = i === curIdx && !terminal;
        const cls = [c.step, done ? c.stepDone : "", active ? c.stepActive : ""].filter(Boolean).join(" ");
        return (
          <div key={st.key} style={{ display: "contents" }}>
            {i > 0 && <div className={`${c.stepLine} ${i <= curIdx || terminal ? c.stepLineDone : ""}`} />}
            <div className={cls}>
              <span className={c.stepDot}>{done ? "✓" : i + 1}</span>
              <span className={c.stepLabel}>{st.label}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function clip(str: string, n: number): string {
  return str.length > n ? str.slice(0, n - 1) + "…" : str;
}
