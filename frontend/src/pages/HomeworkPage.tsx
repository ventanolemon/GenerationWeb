import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useSession } from "../session";
import type {
  AssignmentProgress,
  Partition,
  Subject,
  TeachingAssignment,
} from "../api/types";
import { useAsync } from "../screens/useAsync";
import { fmtDue } from "../screens/format";
import styles from "../styles/screens.module.css";

export default function HomeworkPage() {
  const { role } = useSession();
  const isTeacher = role === "teacher" || role === "admin";
  return (
    <div className={styles.page}>
      <div className={styles.pageHead}>
        <div>
          <h1 className={styles.h1}>Домашки</h1>
          <p className={styles.sub}>
            {isTeacher
              ? "Выдача заданий группам и контроль выполнения"
              : "Задания, выданные вашим группам"}
          </p>
        </div>
      </div>
      {isTeacher ? <TeacherHomework /> : <StudentHomework />}
    </div>
  );
}

// ───────────────────────────── Преподаватель ─────────────────────────────

function TeacherHomework() {
  const { identity } = useSession();
  const teaching = useAsync(() => api.teachingAssignments(identity!), [identity]);
  const myGroups = useAsync(() => api.groupsMine(identity!), [identity]);
  const [progress, setProgress] = useState<AssignmentProgress | null>(null);

  const assignments = teaching.data?.assignments ?? [];

  return (
    <>
      <IssueForm groups={myGroups.data?.groups ?? []} onIssued={teaching.reload} />

      <div className={styles.tableCard}>
        <div className={styles.tableTop}>
          <h3>Мои выдачи</h3>
        </div>
        {teaching.error && <div className={styles.error} style={{ margin: 16 }}>{teaching.error}</div>}
        {teaching.loading && !teaching.data && <div className={styles.state}>Загрузка…</div>}
        {teaching.data && assignments.length === 0 ? (
          <div className={styles.state}>
            <div className={styles.stateBig}>Вы ещё ничего не выдавали</div>
            <div>Выберите задание и группу выше, чтобы выдать домашку.</div>
          </div>
        ) : (
          teaching.data && (
            <div className={styles.tScroll}>
              <table className={styles.t}>
                <thead>
                  <tr>
                    <th>Задание</th>
                    <th>Предмет</th>
                    <th>Группа</th>
                    <th>Срок</th>
                    <th>Сдали</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {assignments.map((a) => (
                    <TeachingRow
                      key={a.id}
                      a={a}
                      onProgress={async () => setProgress(await api.assignmentProgress(identity!, a.id))}
                      onRemove={async () => {
                        await api.deleteAssignment(identity!, a.id);
                        teaching.reload();
                      }}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>

      {progress && <ProgressModal progress={progress} onClose={() => setProgress(null)} />}
    </>
  );
}

function TeachingRow({
  a,
  onProgress,
  onRemove,
}: {
  a: TeachingAssignment;
  onProgress: () => Promise<void>;
  onRemove: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const ratio = a.member_count ? a.solved_count / a.member_count : 0;
  return (
    <tr>
      <td><b>{a.partition_name}</b></td>
      <td>{a.subject_name}</td>
      <td>{a.group_name}</td>
      <td>{a.due_at == null ? <span className={styles.no}>без срока</span> : fmtDue(a.due_at)}</td>
      <td>
        <div className={styles.solvedCell}>
          <span className={styles.lbl}>
            {a.solved_count}/{a.member_count}
          </span>
          <span className={styles.meter}>
            <i style={{ width: `${Math.round(ratio * 100)}%` }} />
          </span>
        </div>
      </td>
      <td className={styles.num}>
        <div style={{ display: "inline-flex", gap: 8 }}>
          <button
            type="button"
            className={`${styles.btn} ${styles.sm}`}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onProgress();
              } finally {
                setBusy(false);
              }
            }}
          >
            Кто сдал
          </button>
          <button
            type="button"
            className={`${styles.btn} ${styles.sm} ${styles.danger}`}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onRemove();
              } finally {
                setBusy(false);
              }
            }}
          >
            Снять
          </button>
        </div>
      </td>
    </tr>
  );
}

function IssueForm({
  groups,
  onIssued,
}: {
  groups: { id: number; name: string }[];
  onIssued: () => void;
}) {
  const { identity } = useSession();
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [partitions, setPartitions] = useState<Partition[]>([]);
  const [partitionId, setPartitionId] = useState<number | null>(null);
  const [groupId, setGroupId] = useState<number | null>(null);
  const [due, setDue] = useState("");
  const [noDue, setNoDue] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.listSubjects().then((s) => {
      setSubjects(s);
      if (s.length) setSubjectId(s[0].id);
    });
  }, []);

  useEffect(() => {
    if (subjectId == null) return;
    api.listPartitions(subjectId).then((p) => {
      setPartitions(p);
      setPartitionId(p.length ? p[0].id : null);
    });
  }, [subjectId]);

  useEffect(() => {
    if (groupId == null && groups.length) setGroupId(groups[0].id);
  }, [groups, groupId]);

  const canIssue = partitionId != null && groupId != null && !busy;

  async function issue() {
    if (partitionId == null || groupId == null) return;
    setBusy(true);
    setErr(null);
    try {
      const dueAt = noDue || !due ? null : Math.floor(new Date(due).getTime() / 1000);
      await api.createAssignment(identity!, {
        partition_id: partitionId,
        group_id: groupId,
        due_at: dueAt,
      });
      onIssued();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.card} style={{ marginBottom: 16 }}>
      <p className={styles.cardTitle}>Выдать задание</p>
      {err && <div className={styles.error}>{err}</div>}
      {groups.length === 0 ? (
        <span className={styles.inlineHint}>
          Вам не назначено ни одной группы — попросите администратора назначить вас.
        </span>
      ) : (
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <Field label="Предмет">
            <select
              className={styles.input}
              value={subjectId ?? ""}
              onChange={(e) => setSubjectId(Number(e.target.value))}
            >
              {subjects.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Задание">
            <select
              className={styles.input}
              value={partitionId ?? ""}
              onChange={(e) => setPartitionId(Number(e.target.value))}
              disabled={partitions.length === 0}
            >
              {partitions.length === 0 && <option>— нет разделов —</option>}
              {partitions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Группа">
            <select
              className={styles.input}
              value={groupId ?? ""}
              onChange={(e) => setGroupId(Number(e.target.value))}
            >
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Срок">
            <input
              className={styles.input}
              type="date"
              value={due}
              disabled={noDue}
              onChange={(e) => setDue(e.target.value)}
            />
          </Field>
          <label className={styles.inlineHint} style={{ cursor: "pointer", paddingBottom: 8 }}>
            <input type="checkbox" checked={noDue} onChange={(e) => setNoDue(e.target.checked)} /> без срока
          </label>
          <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={!canIssue} onClick={issue}>
            Выдать
          </button>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: "var(--text-muted)" }}>
      {label}
      {children}
    </label>
  );
}

// ───────────────────────────── Студент ─────────────────────────────

function StudentHomework() {
  const { identity } = useSession();
  const navigate = useNavigate();
  const { data, error, loading } = useAsync(() => api.myAssignments(identity!), [identity]);
  const assignments = data?.assignments ?? [];

  return (
    <div className={styles.tableCard}>
      <div className={styles.tableTop}>
        <h3>Мои задания</h3>
        <span className={styles.tableHint}>решаются в разделе «Генератор»</span>
      </div>
      {error && <div className={styles.error} style={{ margin: 16 }}>{error}</div>}
      {loading && !data && <div className={styles.state}>Загрузка…</div>}
      {data && assignments.length === 0 ? (
        <div className={styles.state}>
          <div className={styles.stateBig}>Домашек пока нет</div>
          <div>Когда преподаватель выдаст задание вашей группе, оно появится здесь.</div>
        </div>
      ) : (
        data && (
          <div className={styles.tScroll}>
            <table className={styles.t}>
              <thead>
                <tr>
                  <th>Задание</th>
                  <th>Предмет</th>
                  <th>Группа</th>
                  <th>Срок</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {assignments.map((a) => (
                  <tr key={a.id}>
                    <td><b>{a.partition_name}</b></td>
                    <td>{a.subject_name}</td>
                    <td>{a.group_name}</td>
                    <td>{a.due_at == null ? <span className={styles.no}>без срока</span> : fmtDue(a.due_at)}</td>
                    <td className={styles.num}>
                      <button type="button" className={`${styles.btn} ${styles.sm}`} onClick={() => navigate("/")}>
                        Решать
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}
    </div>
  );
}

// ───────────────────────────── Модалка прогресса ─────────────────────────────

function ProgressModal({
  progress,
  onClose,
}: {
  progress: AssignmentProgress;
  onClose: () => void;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const { assignment, students, summary } = progress;

  const statusPill = (s: (typeof students)[number]) => {
    if (s.solved) return <span className={`${styles.pill} ${styles.ok}`}>сдал</span>;
    if (s.attempts > 0) return <span className={`${styles.pill} ${styles.warn}`}>пытался</span>;
    return <span className={`${styles.pill} ${styles.mut}`}>не начал</span>;
  };

  return (
    <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>
        <div className={styles.modalHead}>
          <div>
            <h3>Кто сдал</h3>
            <div className={styles.mSub}>
              {assignment.partition_name} · {assignment.group_name} — сдали {summary.solved} из {summary.members}
            </div>
          </div>
          <button type="button" className={styles.closeX} aria-label="Закрыть" onClick={onClose}>
            ×
          </button>
        </div>
        <div className={styles.modalBody}>
          <table className={styles.t}>
            <thead>
              <tr>
                <th>Студент</th>
                <th className={styles.num}>Попыток</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {students.map((s) => (
                <tr key={s.login}>
                  <td>
                    <div className={styles.who}>
                      <b>{s.fio || s.login}</b>
                      <span className={styles.mono}>{s.login}</span>
                    </div>
                  </td>
                  <td className={styles.num}>{s.attempts}</td>
                  <td>{statusPill(s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
