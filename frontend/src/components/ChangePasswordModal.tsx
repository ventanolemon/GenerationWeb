import { useState } from "react";
import { api, ApiError } from "../api/client";
import Modal from "./Modal";
import mstyles from "../styles/modal.module.css";
import pstyles from "../styles/profile.module.css";

interface Props {
  login: string;
  onClose: () => void;
}

/** Смена пароля: текущий + новый (дважды). Проверка текущего — на сервере. */
export default function ChangePasswordModal({ login, onClose }: Props) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [next2, setNext2] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleSave() {
    if (!current) { setError("Введите текущий пароль."); return; }
    if (next.length < 4) { setError("Новый пароль — не менее 4 символов."); return; }
    if (next !== next2) { setError("Новые пароли не совпадают."); return; }
    setSaving(true);
    setError(null);
    try {
      await api.changePassword({ login, currentPassword: current, newPassword: next });
      setDone(true);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? "Неверный текущий пароль."
          : e instanceof Error ? e.message : String(e)
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Смена пароля" onClose={onClose} width={400}>
      <div className={pstyles.subForm}>
        {done ? (
          <>
            <div className={pstyles.successMsg}>Пароль успешно изменён.</div>
            <div className={mstyles.modalFooter}>
              <button className={mstyles.btnSave} onClick={onClose}>Готово</button>
            </div>
          </>
        ) : (
          <>
            {error && <div className={mstyles.errorMsg}>{error}</div>}
            <div className={mstyles.formRow}>
              <label className={mstyles.formLabel}>Текущий пароль</label>
              <input className={mstyles.formInput} type="password" value={current}
                     onChange={(e) => setCurrent(e.target.value)} autoFocus
                     autoComplete="current-password" />
            </div>
            <div className={mstyles.formRow}>
              <label className={mstyles.formLabel}>Новый пароль</label>
              <input className={mstyles.formInput} type="password" value={next}
                     onChange={(e) => setNext(e.target.value)}
                     autoComplete="new-password" />
            </div>
            <div className={mstyles.formRow}>
              <label className={mstyles.formLabel}>Повторите новый пароль</label>
              <input className={mstyles.formInput} type="password" value={next2}
                     onChange={(e) => setNext2(e.target.value)}
                     autoComplete="new-password" />
            </div>
            <div className={mstyles.modalFooter}>
              <button className={mstyles.btnCancel} onClick={onClose}>Отмена</button>
              <button className={mstyles.btnSave} onClick={handleSave} disabled={saving}>
                {saving ? "Сохранение…" : "Изменить пароль"}
              </button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
