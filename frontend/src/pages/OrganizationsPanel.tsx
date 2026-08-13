import { useMemo, useState } from "react";
import { api } from "../api/client";
import { useSession } from "../session";
import type { MyOrganization, Organization } from "../api/types";
import { useAsync } from "../screens/useAsync";
import styles from "../styles/screens.module.css";

/**
 * Организации (§8 плана).
 *
 * Экран показывает две РАЗНЫЕ вещи, и это главное, что он обязан донести:
 * роль `admin` теперь означает «администратор своей организации», а
 * решения уровня развёртывания — какие пакеты узлов установлены, ключи
 * подписи, выпуски, публичный API — принадлежат администратору
 * развёртывания (`is_superuser`). Это не «админ на уровень выше», а
 * другая ось, и если её не показать, разница между «не хватает прав» и
 * «не ваша организация» будет выглядеть случайной.
 *
 * Поэтому админ организации видит здесь только свою: чужой организации не
 * видно вовсе (§8.1), и сервер на запрос чужой отвечает 404, а не 403.
 */
export default function OrganizationsPanel() {
  const { identity } = useSession();
  const me = useAsync(() => api.myOrganization(identity!), [identity]);

  if (me.error) {
    return <div className={styles.error}>Не удалось загрузить: {me.error}</div>;
  }
  if (!me.data) return <div className={styles.state}>Загрузка…</div>;

  return me.data.is_superuser ? (
    <DeploymentView me={me.data} onChanged={me.reload} />
  ) : (
    <OwnOrganizationView me={me.data} onChanged={me.reload} />
  );
}

// ───────────────────────── Администратор развёртывания ─────────────────

function DeploymentView({
  me,
  onChanged,
}: {
  me: MyOrganization;
  onChanged: () => void;
}) {
  const { identity } = useSession();
  const list = useAsync(() => api.adminListOrganizations(identity!), [identity]);
  const [curId, setCurId] = useState<number | null>(null);

  const orgs = list.data?.organizations ?? [];
  const cur = orgs.find((o) => o.id === curId) ?? orgs[0] ?? null;

  return (
    <>
      <div className={styles.tableCard} style={{ marginBottom: 16 }}>
        <div className={styles.tableTop}>
          <h3>Вы — администратор развёртывания</h3>
          <span className={styles.pill + " " + styles.ok}>is_superuser</span>
        </div>
        <p className={styles.inlineHint} style={{ padding: "0 16px 12px" }}>
          Пакеты узлов, ключи подписи, выпуски приложения и публичный API —
          решения уровня развёртывания, они за вами. Набор установленных
          пакетов один на всех: иначе вопрос «какой код здесь исполняется»
          перешёл бы к организации.
        </p>
      </div>

      <CreateOrganizationForm
        onCreated={(o) => {
          setCurId(o.id);
          list.reload();
        }}
      />

      {list.error && (
        <div className={styles.error}>Не удалось загрузить: {list.error}</div>
      )}
      {list.loading && !list.data && (
        <div className={styles.state}>Загрузка…</div>
      )}

      {cur && (
        <div className={styles.md}>
          <div className={styles.gList}>
            {orgs.map((o) => (
              <button
                key={o.id}
                type="button"
                className={styles.gItem}
                aria-current={o.id === cur.id}
                onClick={() => setCurId(o.id)}
              >
                <b>{o.name}</b>
                <span className={styles.cnt}>{o.member_count ?? 0}</span>
              </button>
            ))}
          </div>
          <OrganizationCard
            orgId={cur.id}
            canManage
            viewerLogin={me.login}
            onChanged={() => {
              list.reload();
              onChanged();
            }}
          />
        </div>
      )}
    </>
  );
}

function CreateOrganizationForm({
  onCreated,
}: {
  onCreated: (org: Organization) => void;
}) {
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
      const org = await api.adminCreateOrganization(identity!, trimmed);
      setName("");
      onCreated(org);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.tableCard} style={{ marginBottom: 16 }}>
      <div className={styles.tableTop}>
        <h3>Новая организация</h3>
      </div>
      <div style={{ display: "flex", gap: 8, padding: "0 16px 16px" }}>
        <input
          className={styles.input}
          placeholder="Название — например, «Кафедра физики»"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          style={{ flex: 1 }}
        />
        <button type="button" disabled={busy || !name.trim()} onClick={submit}>
          {busy ? "Создаём…" : "Создать"}
        </button>
      </div>
      {err && (
        <div className={styles.error} style={{ margin: "0 16px 16px" }}>
          {err}
        </div>
      )}
    </div>
  );
}

// ───────────────────────── Админ своей организации ─────────────────────

function OwnOrganizationView({
  me,
  onChanged,
}: {
  me: MyOrganization;
  onChanged: () => void;
}) {
  if (!me.organization) {
    return (
      <div className={styles.state}>
        <div className={styles.stateBig}>Вы не состоите в организации</div>
        <div>
          Пока вас не примут, общий каталог недоступен: содержимое живёт
          внутри организаций. Попросите администратора развёртывания принять
          вас.
        </div>
      </div>
    );
  }

  return (
    <OrganizationCard
      orgId={me.organization.id}
      canManage={false}
      viewerLogin={me.login}
      onChanged={onChanged}
    />
  );
}

// ───────────────────────── Карточка организации ────────────────────────

function OrganizationCard({
  orgId,
  canManage,
  viewerLogin,
  onChanged,
}: {
  orgId: number;
  canManage: boolean;
  viewerLogin: string;
  onChanged: () => void;
}) {
  const { identity } = useSession();
  const org = useAsync(
    () => api.adminGetOrganization(identity!, orgId),
    [identity, orgId],
  );
  const usersQ = useAsync(() => api.adminListUsers(identity!), [identity]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [addLogin, setAddLogin] = useState("");

  const fioByLogin = useMemo(() => {
    const m = new Map<string, string>();
    (usersQ.data?.users ?? []).forEach((u) => m.set(u.login, u.fio || u.login));
    return m;
  }, [usersQ.data]);

  // Владельцем организации может стать только администратор в ней — так
  // проверяет сервер. Предлагать кнопку остальным значит предлагать
  // действие, которое гарантированно откажет.
  const roleByLogin = useMemo(() => {
    const m = new Map<string, string>();
    (usersQ.data?.users ?? []).forEach((u) => m.set(u.login, u.role));
    return m;
  }, [usersQ.data]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setErr(null);
    try {
      await action();
      org.reload();
      usersQ.reload();
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (org.error) {
    return <div className={styles.error}>Не удалось загрузить: {org.error}</div>;
  }
  if (!org.data) return <div className={styles.state}>Загрузка…</div>;

  const members = org.data.members ?? [];
  const isOwner = org.data.owner_login === viewerLogin;

  return (
    <div className={styles.tableCard}>
      <div className={styles.tableTop}>
        <h3>{org.data.name}</h3>
        <span className={styles.pill + " " + styles.mut}>
          {members.length} чел.
        </span>
      </div>

      <div style={{ padding: "0 16px 12px" }}>
        <div style={{ marginBottom: 8 }}>
          Владелец:{" "}
          {org.data.owner_login ? (
            <b>{fioByLogin.get(org.data.owner_login) ?? org.data.owner_login}</b>
          ) : (
            <span className={styles.no}>не назначен</span>
          )}
          {isOwner && <span className={styles.badgeYou}>это вы</span>}
        </div>
        <span className={styles.inlineHint}>
          Владелец у организации ровно один, и единственная операция —
          передача. Организацию, оставшуюся без доступного владельца,
          переназначает администратор развёртывания — иначе «владельца нельзя
          понизить» превратилось бы в ловушку.
        </span>
      </div>

      {canManage && (
        <div style={{ display: "flex", gap: 8, padding: "0 16px 12px" }}>
          <input
            className={styles.input}
            placeholder="Переименовать"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            style={{ flex: 1 }}
          />
          <button
            type="button"
            disabled={busy || !newName.trim()}
            onClick={() =>
              run(async () => {
                await api.adminRenameOrganization(
                  identity!,
                  orgId,
                  newName.trim(),
                );
                setNewName("");
              })
            }
          >
            Переименовать
          </button>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, padding: "0 16px 12px" }}>
        <input
          className={styles.input}
          placeholder="Логин — принять в организацию"
          value={addLogin}
          onChange={(e) => setAddLogin(e.target.value)}
          style={{ flex: 1 }}
        />
        <button
          type="button"
          disabled={busy || !addLogin.trim()}
          onClick={() =>
            run(async () => {
              await api.adminAddToOrganization(
                identity!,
                orgId,
                addLogin.trim(),
              );
              setAddLogin("");
            })
          }
        >
          Принять
        </button>
      </div>

      {err && (
        <div className={styles.error} style={{ margin: "0 16px 12px" }}>
          {err}
        </div>
      )}

      <div className={styles.tScroll}>
        <table className={styles.t}>
          <thead>
            <tr>
              <th>Участник</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {members.length === 0 ? (
              <tr>
                <td colSpan={2}>
                  <div className={styles.state}>Пока никого</div>
                </td>
              </tr>
            ) : (
              members.map((login) => (
                <tr key={login}>
                  <td>
                    <div className={styles.who}>
                      <b>{fioByLogin.get(login) ?? login}</b>
                      <span className={styles.mono}>{login}</span>
                    </div>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 8 }}>
                      {org.data!.owner_login === login ? (
                        <span className={styles.pill + " " + styles.ok}>
                          владелец
                        </span>
                      ) : (
                        <>
                          {(isOwner || canManage) &&
                            roleByLogin.get(login) === "admin" && (
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() =>
                                  run(() =>
                                    api.adminTransferOwnership(
                                      identity!,
                                      orgId,
                                      login,
                                    ),
                                  )
                                }
                                title="Передать владение организацией"
                              >
                                Сделать владельцем
                              </button>
                            )}
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() =>
                              run(() =>
                                api.adminRemoveFromOrganization(
                                  identity!,
                                  orgId,
                                  login,
                                ),
                              )
                            }
                          >
                            Исключить
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div
        style={{ padding: "10px 16px", borderTop: "1px solid var(--border)" }}
      >
        <span className={styles.inlineHint}>
          Перевод между организациями меняет весь видимый набор предметов —
          десктоп пересоберёт его при следующей синхронизации.
        </span>
      </div>
    </div>
  );
}
