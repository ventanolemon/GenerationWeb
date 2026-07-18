import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { useSession } from "../session";
import type { AdminUser, Group, Role } from "../api/types";
import { useAsync } from "../screens/useAsync";
import { RU_ROLE } from "../screens/format";
import styles from "../styles/screens.module.css";

type Sub = "users" | "groups" | "perms";
const SUBS: { key: Sub; label: string }[] = [
  { key: "users", label: "Пользователи и роли" },
  { key: "groups", label: "Группы" },
  { key: "perms", label: "Права по ролям" },
];

export default function AdminPage() {
  const [sub, setSub] = useState<Sub>("users");
  return (
    <div className={styles.page}>
      <div className={styles.pageHead}>
        <div>
          <h1 className={styles.h1}>Администрирование</h1>
          <p className={styles.sub}>
            Роли и права применяются у пользователя при следующем входе
          </p>
        </div>
        <div className={styles.seg} role="group" aria-label="Раздел администрирования">
          {SUBS.map((s) => (
            <button key={s.key} type="button" aria-pressed={sub === s.key} onClick={() => setSub(s.key)}>
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {sub === "users" && <UsersPanel />}
      {sub === "groups" && <GroupsPanel />}
      {sub === "perms" && <PermsMatrix />}
    </div>
  );
}

// ───────────────────────── Пользователи и роли ─────────────────────────

function UsersPanel() {
  const { identity } = useSession();
  const viewer = identity!.login;
  const { data, error, loading, reload } = useAsync(() => api.adminListUsers(identity!), [identity]);
  const [query, setQuery] = useState("");

  const users = data?.users ?? [];
  const adminCount = users.filter((u) => u.role === "admin").length;
  const filtered = users.filter((u) => {
    const q = query.trim().toLowerCase();
    return !q || `${u.fio} ${u.login} ${u.group}`.toLowerCase().includes(q);
  });

  return (
    <div className={styles.tableCard}>
      <div className={styles.tableTop}>
        <h3>Пользователи</h3>
        <input
          className={styles.input}
          placeholder="Поиск по имени, логину, группе"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ minWidth: 260 }}
        />
      </div>

      {error && <div className={styles.error} style={{ margin: 16 }}>Не удалось загрузить: {error}</div>}
      {loading && !data && <div className={styles.state}>Загрузка…</div>}

      {data && (
        <div className={styles.tScroll}>
          <table className={styles.t}>
            <thead>
              <tr>
                <th>Пользователь</th>
                <th>Группа</th>
                <th>Роль</th>
                <th>Регистрация</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={4}>
                    <div className={styles.state}>
                      <div className={styles.stateBig}>Никого не найдено</div>
                      <div>Измените запрос поиска.</div>
                    </div>
                  </td>
                </tr>
              ) : (
                filtered.map((u) => (
                  <tr key={u.login}>
                    <td>
                      <div className={styles.who}>
                        <b>{u.fio || u.login}</b>
                        <span className={styles.mono}>{u.login}</span>
                      </div>
                    </td>
                    <td>{u.group ? u.group : <span className={styles.no}>—</span>}</td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <RoleCell
                          user={u}
                          isViewer={u.login === viewer}
                          isLastAdmin={u.role === "admin" && adminCount <= 1}
                          onChange={async (role) => {
                            await api.adminChangeRole(identity!, u.login, role);
                            reload();
                          }}
                        />
                        {u.login === viewer && <span className={styles.badgeYou}>это вы</span>}
                      </div>
                    </td>
                    <td title={new Date(u.created_at * 1000).toLocaleString("ru-RU")}>
                      {monthsAgo(u.created_at)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ padding: "10px 16px", borderTop: "1px solid var(--border)" }}>
        <span className={styles.inlineHint}>
          ⚠ Нельзя изменить свою роль и нельзя понизить последнего администратора.
        </span>
      </div>
    </div>
  );
}

const ROLE_OPTIONS: Role[] = ["student", "teacher", "admin"];

function RoleCell({
  user,
  isViewer,
  isLastAdmin,
  onChange,
}: {
  user: AdminUser;
  isViewer: boolean;
  isLastAdmin: boolean;
  onChange: (role: Role) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<Role | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function close() {
    setOpen(false);
    setPending(null);
    setErr(null);
  }

  async function confirm(role: Role) {
    setErr(null);
    try {
      await onChange(role);
      close();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className={styles.roleSel} ref={ref}>
      <button
        type="button"
        className={styles.roleTrigger}
        disabled={isViewer}
        title={isViewer ? "Нельзя изменить свою роль" : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        {RU_ROLE[user.role]}
        {!isViewer && <span className={styles.cv}>▾</span>}
      </button>

      {open && (
        <div className={`${styles.pop} ${isLastAdmin && pending && pending !== "admin" ? styles.warnPop : ""}`}>
          {isLastAdmin && pending && pending !== "admin" ? (
            <>
              <div className={styles.warnLine}>
                <span>▲</span>
                <span>Нельзя понизить последнего администратора — иначе некому будет управлять ролями.</span>
              </div>
              <div className={styles.popRow}>
                <button type="button" className={`${styles.btn} ${styles.sm}`} onClick={close}>
                  Понятно
                </button>
              </div>
            </>
          ) : pending ? (
            <>
              <h4>Подтвердите</h4>
              <p>
                Изменить роль <b>{user.fio || user.login}</b>: {RU_ROLE[user.role]} → <b>{RU_ROLE[pending]}</b>?
              </p>
              {err && <div className={styles.error} style={{ marginBottom: 10 }}>{err}</div>}
              <div className={styles.popRow}>
                <button type="button" className={`${styles.btn} ${styles.sm}`} onClick={() => setPending(null)}>
                  Отмена
                </button>
                <button
                  type="button"
                  className={`${styles.btn} ${styles.sm} ${styles.primary}`}
                  onClick={() => confirm(pending)}
                >
                  Подтвердить
                </button>
              </div>
            </>
          ) : (
            <>
              <h4>Сменить роль</h4>
              <p>
                {user.fio || user.login} · <span className={styles.mono}>{user.login}</span>
              </p>
              {ROLE_OPTIONS.map((r) => (
                <button
                  key={r}
                  type="button"
                  className={`${styles.btn} ${styles.sm} ${styles.roleOpt}`}
                  disabled={r === user.role}
                  onClick={() => setPending(r)}
                >
                  {r === user.role ? "● " : ""}
                  {RU_ROLE[r]}
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ───────────────────────────── Группы ─────────────────────────────

function GroupsPanel() {
  const { identity } = useSession();
  const { data, error, loading, reload } = useAsync(() => api.adminListGroups(identity!), [identity]);
  const usersQ = useAsync(() => api.adminListUsers(identity!), [identity]);
  const fioByLogin = useMemo(() => {
    const m = new Map<string, string>();
    (usersQ.data?.users ?? []).forEach((u) => m.set(u.login, u.fio || u.login));
    return m;
  }, [usersQ.data]);

  const groups = data?.groups ?? [];
  const [curId, setCurId] = useState<number | null>(null);
  const cur = groups.find((g) => g.id === curId) ?? groups[0] ?? null;

  return (
    <>
      <CreateGroupForm
        onCreated={(g) => {
          setCurId(g.id);
          reload();
        }}
      />

      {error && <div className={styles.error}>Не удалось загрузить группы: {error}</div>}
      {loading && !data && <div className={styles.state}>Загрузка…</div>}
      {data && groups.length === 0 && (
        <div className={styles.state}>
          <div className={styles.stateBig}>Групп пока нет</div>
          <div>Создайте первую группу — потом назначите преподавателей и студентов.</div>
        </div>
      )}
      {data && groups.length > 0 && cur && (
        <div className={styles.md}>
          <div className={styles.gList}>
            {groups.map((g) => (
              <button
                key={g.id}
                type="button"
                className={styles.gItem}
                aria-current={g.id === cur.id}
                onClick={() => setCurId(g.id)}
              >
                <b>{g.name}</b>
                <span className={styles.cnt}>{g.member_count}</span>
              </button>
            ))}
          </div>
          <Roster group={cur} fioByLogin={fioByLogin} onChanged={reload} />
        </div>
      )}
    </>
  );
}

function CreateGroupForm({ onCreated }: { onCreated: (group: Group) => void }) {
  const { identity } = useSession();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    setErr(null);
    try {
      const group = await api.adminCreateGroup(identity!, trimmed);
      setName("");
      onCreated(group);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.card} style={{ marginBottom: 16 }}>
      <p className={styles.cardTitle}>Новая группа</p>
      {err && <div className={styles.error}>{err}</div>}
      <div className={styles.addRow}>
        <input
          className={styles.input}
          style={{ flex: 1 }}
          placeholder="Название группы"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <button
          type="button"
          className={`${styles.btn} ${styles.primary}`}
          disabled={!name.trim() || busy}
          onClick={submit}
        >
          Создать
        </button>
      </div>
    </div>
  );
}

function Roster({
  group,
  fioByLogin,
  onChanged,
}: {
  group: Group;
  fioByLogin: Map<string, string>;
  onChanged: () => void;
}) {
  const { identity } = useSession();
  const [teacherLogin, setTeacherLogin] = useState("");
  const [studentLogin, setStudentLogin] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  const memberRow = (login: string, remove: () => Promise<unknown>) => (
    <div className={styles.memberRow} key={login}>
      <span className={styles.who}>
        <b>{fioByLogin.get(login) ?? login}</b>
        <span className={styles.mono}>{login}</span>
      </span>
      <button type="button" className={styles.x} title="Убрать" onClick={() => run(remove)}>
        ×
      </button>
    </div>
  );

  return (
    <div className={styles.rosterCol}>
      {err && <div className={styles.error}>{err}</div>}

      <div className={styles.card}>
        <p className={styles.cardTitle}>Преподаватели — {group.name}</p>
        {group.teachers.length === 0 ? (
          <span className={styles.inlineHint}>Никто не назначен</span>
        ) : (
          group.teachers.map((t) =>
            memberRow(t, () => api.adminUnassignTeacher(identity!, group.id, t)),
          )
        )}
        <div className={styles.addRow}>
          <input
            className={styles.input}
            style={{ flex: 1 }}
            placeholder="логин преподавателя"
            value={teacherLogin}
            onChange={(e) => setTeacherLogin(e.target.value)}
          />
          <button
            type="button"
            className={styles.btn}
            disabled={!teacherLogin.trim()}
            onClick={() =>
              run(async () => {
                await api.adminAssignTeacher(identity!, group.id, teacherLogin.trim());
                setTeacherLogin("");
              })
            }
          >
            Назначить
          </button>
        </div>
      </div>

      <div className={styles.card}>
        <p className={styles.cardTitle}>Студенты ({group.member_count})</p>
        {group.members.map((m) =>
          memberRow(m, () => api.adminRemoveMember(identity!, group.id, m)),
        )}
        <div className={styles.addRow}>
          <input
            className={styles.input}
            style={{ flex: 1 }}
            placeholder="логин студента"
            value={studentLogin}
            onChange={(e) => setStudentLogin(e.target.value)}
          />
          <button
            type="button"
            className={styles.btn}
            disabled={!studentLogin.trim()}
            onClick={() =>
              run(async () => {
                await api.adminAddMember(identity!, group.id, studentLogin.trim());
                setStudentLogin("");
              })
            }
          >
            Добавить
          </button>
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────── Права по ролям ────────────────────────────

type Cap = boolean | "own" | "soon";
const CAPS: [string, [string, Cap, Cap, Cap][]][] = [
  [
    "Контент",
    [
      ["Решать задания, видеть свою статистику", true, true, true],
      ["Создавать и править свои предметы/разделы", false, true, true],
      ["Скрывать/удалять свои разделы", false, true, true],
      ["Править встроенные (системные) предметы", false, false, true],
    ],
  ],
  [
    "ИИ-контур",
    [
      ["Запускать генерацию через ИИ", false, true, true],
      ["Утверждать сгенерированные задания", false, "own", true],
    ],
  ],
  [
    "Аналитика",
    [
      ["Аналитика по своим предметам", false, true, true],
      ["Глобальная аналитика по всем предметам", false, false, true],
    ],
  ],
  [
    "Администрирование",
    [
      ["Список пользователей, смена ролей", false, false, true],
      ["Группы и назначение преподавателей", false, false, true],
      ["Выдача домашних заданий", false, true, true],
    ],
  ],
];

function Cell({ v }: { v: Cap }) {
  if (v === true) return <span className={styles.yes} title="доступно">✓</span>;
  if (v === false) return <span className={styles.no} title="недоступно">—</span>;
  if (v === "own") return <span className={styles.own}>✓ своё</span>;
  return <span className={styles.soon}>скоро</span>;
}

function PermsMatrix() {
  return (
    <div className={styles.tableCard}>
      <div className={styles.tScroll}>
        <table className={styles.matrix}>
          <thead>
            <tr>
              <th>Возможность</th>
              <th className={styles.role}>студент</th>
              <th className={styles.role}>преподаватель</th>
              <th className={styles.role}>админ</th>
            </tr>
          </thead>
          <tbody>
            {CAPS.map(([cat, rows]) => (
              <Fragment key={cat}>
                <tr className={styles.cat}>
                  <td colSpan={4}>{cat}</td>
                </tr>
                {rows.map(([label, s, t, a]) => (
                  <tr key={label}>
                    <td>{label}</td>
                    <td className={styles.cell}><Cell v={s} /></td>
                    <td className={styles.cell}><Cell v={t} /></td>
                    <td className={styles.cell}><Cell v={a} /></td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ padding: "10px 16px", borderTop: "1px solid var(--border)" }}>
        <span className={styles.inlineHint}>
          Роль назначается целиком. <span className={styles.own}>✓ своё</span> — только для своих
          предметов/групп; <span className={styles.soon}>скоро</span> — в разработке.
        </span>
      </div>
    </div>
  );
}

// ──────────────────────────── утилиты ────────────────────────────

function monthsAgo(epoch: number): string {
  if (!epoch) return "—";
  const d = new Date(epoch * 1000);
  const now = new Date();
  const m = (now.getFullYear() - d.getFullYear()) * 12 + now.getMonth() - d.getMonth();
  return m <= 0 ? "в этом месяце" : `${m} мес назад`;
}
