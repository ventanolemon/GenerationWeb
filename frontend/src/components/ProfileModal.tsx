import { useEffect, useMemo, useState } from "react";
import type { UserInfo, UserStats, WordStatEntry } from "../api/types";
import { api } from "../api/client";
import Modal from "./Modal";
import EditProfileModal from "./EditProfileModal";
import ChangePasswordModal from "./ChangePasswordModal";
import { initials, avatarBackground, formatLastSeen } from "../utils/user";
import styles from "../styles/profile.module.css";

interface Props {
  /** Авторизованный пользователь или null для гостя. */
  user: UserInfo | null;
  /** login (авторизованный) или гостевой UUID — для запроса статистики. */
  userId: string;
  onClose: () => void;
  /** Профиль обновлён — синхронизировать состояние/localStorage в App. */
  onUserUpdated: (user: UserInfo) => void;
  /** Гость нажал «Зарегистрироваться». */
  onRequestRegister: () => void;
}

function rowClass(w: WordStatEntry): string {
  const denom = w.times_correct + w.times_wrong;
  if (denom === 0) return "";
  if (w.times_wrong >= w.times_correct || (w.accuracy ?? 0) < 0.5)
    return styles.rowProblem;
  if ((w.accuracy ?? 0) >= 0.8) return styles.rowMastered;
  return styles.rowNeutral;
}

export default function ProfileModal({
  user, userId, onClose, onUserUpdated, onRequestRegister,
}: Props) {
  const [stats, setStats] = useState<UserStats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(false);
  const [changingPw, setChangingPw] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.getStats(userId)
      .then((s) => { if (!cancelled) setStats(s); })
      .catch((e) => { if (!cancelled) setStatsError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [userId]);

  const displayName = user ? user.fio || user.login : "Гость";

  const filteredWords = useMemo(() => {
    if (!stats) return [];
    const q = search.trim().toLowerCase();
    const words = q
      ? stats.words.filter(
          (w) => w.term.toLowerCase().includes(q) ||
                 w.translation.toLowerCase().includes(q))
      : stats.words;
    // Проблемные слова — наверх, затем по времени показа.
    return [...words].sort((a, b) => {
      const aw = a.times_wrong - a.times_correct;
      const bw = b.times_wrong - b.times_correct;
      if (aw !== bw) return bw - aw;
      return b.last_seen - a.last_seen;
    });
  }, [stats, search]);

  const accuracyPct = stats ? Math.round(stats.summary.accuracy * 100) : 0;

  return (
    <Modal title="Профиль" onClose={onClose} width={720}>
      {/* Шапка */}
      <div className={styles.header}>
        <span
          className={styles.avatar}
          style={{ background: avatarBackground(user?.avatar_color) }}
        >
          {user ? initials(displayName) : "Г"}
        </span>
        <div className={styles.headMeta}>
          <h2 className={styles.name}>{displayName}</h2>
          <div className={styles.subline}>
            {user ? (
              <>
                <span className={styles.chip}>@{user.login}</span>
                {user.group && <span>{user.group}</span>}
                {user.email && <span>{user.email}</span>}
              </>
            ) : (
              <span className={`${styles.chip} ${styles.guestBadge}`}>
                Гостевой режим
              </span>
            )}
          </div>
        </div>
      </div>

      {user?.about && <div className={styles.about}>{user.about}</div>}

      {/* Действия / гостевой призыв */}
      {user ? (
        <div className={styles.actions}>
          <button onClick={() => setEditing(true)}>Редактировать профиль</button>
          <button onClick={() => setChangingPw(true)}>Сменить пароль</button>
        </div>
      ) : (
        <div className={styles.guestCta}>
          <div className={styles.guestCtaText}>
            <strong>Вы занимаетесь как гость</strong>
            История ответов сохраняется только в этом браузере и сбросится
            при перезапуске сервера. Зарегистрируйтесь, чтобы сохранять прогресс.
          </div>
          <button onClick={onRequestRegister}>Зарегистрироваться</button>
        </div>
      )}

      {/* Сводка статистики */}
      <h3 className={styles.sectionTitle}>Статистика английского</h3>
      {loading ? (
        <div className={styles.empty}>Загрузка статистики…</div>
      ) : statsError ? (
        <div className={styles.empty}>Не удалось загрузить статистику: {statsError}</div>
      ) : stats && stats.summary.total_terms > 0 ? (
        <>
          <div className={styles.cards}>
            <div className={styles.card}>
              <div className={styles.cardValue}>{stats.summary.total_terms}</div>
              <div className={styles.cardLabel}>Слов</div>
            </div>
            <div className={styles.card}>
              <div className={`${styles.cardValue} ${styles.cardValueAccent}`}>{accuracyPct}%</div>
              <div className={styles.cardLabel}>Точность</div>
            </div>
            <div className={styles.card}>
              <div className={styles.cardValue}>{stats.summary.total_shown}</div>
              <div className={styles.cardLabel}>Показов</div>
            </div>
            <div className={styles.card}>
              <div className={styles.cardValue}>{stats.summary.total_correct}</div>
              <div className={styles.cardLabel}>Верно</div>
            </div>
            <div className={styles.card}>
              <div className={styles.cardValue}>{stats.summary.total_wrong}</div>
              <div className={styles.cardLabel}>Ошибок</div>
            </div>
          </div>

          <div className={styles.searchRow}>
            <input
              className={styles.search}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по слову или переводу…"
            />
          </div>

          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Слово</th>
                  <th>Перевод</th>
                  <th className={styles.num}>Показов</th>
                  <th className={styles.num}>Верно</th>
                  <th className={styles.num}>Ошибок</th>
                  <th className={styles.num}>Точность</th>
                  <th>Последний раз</th>
                </tr>
              </thead>
              <tbody>
                {filteredWords.map((w) => (
                  <tr key={w.term} className={rowClass(w)}>
                    <td className={styles.term}>{w.term}</td>
                    <td className={styles.translation}>{w.translation || "—"}</td>
                    <td className={styles.num}>{w.times_shown}</td>
                    <td className={styles.num}>{w.times_correct}</td>
                    <td className={styles.num}>{w.times_wrong}</td>
                    <td className={styles.num}>
                      {w.accuracy === null ? "—" : `${Math.round(w.accuracy * 100)}%`}
                    </td>
                    <td>{formatLastSeen(w.last_seen)}</td>
                  </tr>
                ))}
                {filteredWords.length === 0 && (
                  <tr>
                    <td colSpan={7} className={styles.empty}>Ничего не найдено.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className={styles.empty}>
          Статистика пока пуста. Пройдите словарный тренажёр — здесь появятся
          ваши успехи и ошибки.
        </div>
      )}

      {editing && user && (
        <EditProfileModal
          user={user}
          onSaved={(u) => { onUserUpdated(u); setEditing(false); }}
          onClose={() => setEditing(false)}
        />
      )}
      {changingPw && user && (
        <ChangePasswordModal login={user.login} onClose={() => setChangingPw(false)} />
      )}
    </Modal>
  );
}
