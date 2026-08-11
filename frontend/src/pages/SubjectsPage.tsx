import { useState } from "react";
import { api } from "../api/client";
import { useSession } from "../session";
import type { ManagedSubject } from "../api/types";
import { useAsync } from "../screens/useAsync";
import styles from "../styles/screens.module.css";

/**
 * Редактор предметов.
 *
 * До него предмет нельзя было завести через продукт ВООБЩЕ: предметы
 * появлялись только из bootstrap при старте сервиса, и преподавателю,
 * которому нужен свой, оставалось просить администратора править БД.
 *
 * Показываются только видимые: своя организация, свои выдачи, встроенные
 * (§8.1). Встроенные помечены отдельно — они принадлежат продукту, видны
 * всем организациям сразу, и трогать их может лишь администратор
 * развёртывания.
 */
export default function SubjectsPage() {
  const { identity, role } = useSession();
  const q = useAsync(() => api.listManagedSubjects(identity!), [identity]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");

  const canCreate = role === "teacher" || role === "admin";

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setErr(null);
    try {
      await action();
      q.reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const subjects = q.data?.subjects ?? [];

  return (
    <div className={styles.page}>
      <div className={styles.pageHead}>
        <div>
          <h1 className={styles.h1}>Предметы</h1>
          <p className={styles.sub}>
            Свои и выданные вам. Встроенные принадлежат продукту и видны
            всем организациям
          </p>
        </div>
      </div>

      {canCreate && (
        <div className={styles.tableCard} style={{ marginBottom: 16 }}>
          <div className={styles.tableTop}>
            <h3>Новый предмет</h3>
          </div>
          <div style={{ display: "flex", gap: 8, padding: "0 16px 16px" }}>
            <input
              className={styles.input}
              placeholder="Название — например, «Оптика»"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && name.trim()) {
                  void run(async () => {
                    await api.createSubject(identity!, name.trim());
                    setName("");
                  });
                }
              }}
              style={{ flex: 1 }}
            />
            <button
              type="button"
              disabled={busy || !name.trim()}
              onClick={() =>
                run(async () => {
                  await api.createSubject(identity!, name.trim());
                  setName("");
                })
              }
            >
              {busy ? "Создаём…" : "Создать"}
            </button>
          </div>
          <p className={styles.inlineHint} style={{ padding: "0 16px 12px" }}>
            Предмет заводится вашим: он попадёт в ваше личное хранилище и в
            вашу организацию. Сделать его встроенным — отдельное решение
            администратора развёртывания.
          </p>
        </div>
      )}

      {err && <div className={styles.error} style={{ marginBottom: 12 }}>{err}</div>}
      {q.error && <div className={styles.error}>Не удалось загрузить: {q.error}</div>}
      {q.loading && !q.data && <div className={styles.state}>Загрузка…</div>}

      {q.data && (
        <div className={styles.tableCard}>
          <div className={styles.tScroll}>
            <table className={styles.t}>
              <thead>
                <tr>
                  <th>Предмет</th>
                  <th>Разделов</th>
                  <th>Где лежит</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {subjects.length === 0 ? (
                  <tr>
                    <td colSpan={4}>
                      <div className={styles.state}>
                        <div className={styles.stateBig}>Предметов пока нет</div>
                        <div>Заведите первый — потом добавите в него разделы.</div>
                      </div>
                    </td>
                  </tr>
                ) : (
                  subjects.map((s) => (
                    <SubjectRow
                      key={s.id}
                      subject={s}
                      busy={busy}
                      editing={editing === s.id}
                      draft={draft}
                      onDraft={setDraft}
                      onStartEdit={() => {
                        setEditing(s.id);
                        setDraft(s.name);
                      }}
                      onCancel={() => setEditing(null)}
                      onSave={() =>
                        run(async () => {
                          await api.renameSubject(identity!, s.id, draft.trim());
                          setEditing(null);
                        })
                      }
                      onDelete={() =>
                        run(() => api.deleteSubject(identity!, s.id))
                      }
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>
          <div
            style={{ padding: "10px 16px", borderTop: "1px solid var(--border)" }}
          >
            <span className={styles.inlineHint}>
              Удалить можно только пустой предмет: каскад снёс бы разделы,
              в том числе приехавшие с другого устройства.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function SubjectRow({
  subject,
  busy,
  editing,
  draft,
  onDraft,
  onStartEdit,
  onCancel,
  onSave,
  onDelete,
}: {
  subject: ManagedSubject;
  busy: boolean;
  editing: boolean;
  draft: string;
  onDraft: (v: string) => void;
  onStartEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
  onDelete: () => void;
}) {
  // Встроенный правит только администратор развёртывания, чужой — его
  // владелец. Кнопку, которая гарантированно откажет, не показываем.
  const editable = subject.is_mine;

  return (
    <tr>
      <td>
        {editing ? (
          <input
            className={styles.input}
            value={draft}
            autoFocus
            onChange={(e) => onDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && draft.trim()) onSave();
              if (e.key === "Escape") onCancel();
            }}
          />
        ) : (
          <div className={styles.who}>
            <b>{subject.name}</b>
            {subject.owner && (
              <span className={styles.mono}>{subject.owner}</span>
            )}
          </div>
        )}
      </td>
      <td>{subject.partition_count}</td>
      <td>
        {subject.is_builtin ? (
          <span
            className={`${styles.pill} ${styles.mut}`}
            title="Принадлежит продукту, виден всем организациям"
          >
            встроенный
          </span>
        ) : subject.is_mine ? (
          <span className={`${styles.pill} ${styles.ok}`}>ваш</span>
        ) : (
          <span className={styles.pill}>выдан вам</span>
        )}
      </td>
      <td>
        <div style={{ display: "flex", gap: 8 }}>
          {editing ? (
            <>
              <button type="button" disabled={busy || !draft.trim()} onClick={onSave}>
                Сохранить
              </button>
              <button type="button" disabled={busy} onClick={onCancel}>
                Отмена
              </button>
            </>
          ) : editable ? (
            <>
              <button type="button" disabled={busy} onClick={onStartEdit}>
                Переименовать
              </button>
              <button
                type="button"
                disabled={busy || subject.partition_count > 0}
                title={
                  subject.partition_count > 0
                    ? "Сначала перенесите или удалите разделы"
                    : "Удалить предмет"
                }
                onClick={onDelete}
              >
                Удалить
              </button>
            </>
          ) : (
            <span className={styles.no}>—</span>
          )}
        </div>
      </td>
    </tr>
  );
}
