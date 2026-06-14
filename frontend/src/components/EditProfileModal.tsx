import { useState } from "react";
import type { UserInfo } from "../api/types";
import { api } from "../api/client";
import Modal from "./Modal";
import { AVATAR_COLORS } from "../utils/user";
import mstyles from "../styles/modal.module.css";
import pstyles from "../styles/profile.module.css";

interface Props {
  user: UserInfo;
  onSaved: (updated: UserInfo) => void;
  onClose: () => void;
}

/** Редактирование полей профиля: ФИО, группа, email, о себе, цвет аватара. */
export default function EditProfileModal({ user, onSaved, onClose }: Props) {
  const [fio, setFio] = useState(user.fio ?? "");
  const [group, setGroup] = useState(user.group ?? "");
  const [email, setEmail] = useState(user.email ?? "");
  const [about, setAbout] = useState(user.about ?? "");
  const [color, setColor] = useState(user.avatar_color ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (!fio.trim()) { setError("Введите имя."); return; }
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateProfile(user.login, {
        fio: fio.trim(),
        group: group.trim(),
        email: email.trim(),
        about: about.trim(),
        avatar_color: color,
      });
      onSaved(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Редактирование профиля" onClose={onClose} width={460}>
      <div className={pstyles.subForm}>
        {error && <div className={mstyles.errorMsg}>{error}</div>}

        <div className={mstyles.formRow}>
          <label className={mstyles.formLabel}>Имя (ФИО)</label>
          <input className={mstyles.formInput} value={fio}
                 onChange={(e) => setFio(e.target.value)} autoFocus />
        </div>
        <div className={mstyles.formRow}>
          <label className={mstyles.formLabel}>Группа</label>
          <input className={mstyles.formInput} value={group}
                 onChange={(e) => setGroup(e.target.value)} />
        </div>
        <div className={mstyles.formRow}>
          <label className={mstyles.formLabel}>Email</label>
          <input className={mstyles.formInput} type="email" value={email}
                 onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className={mstyles.formRow}>
          <label className={mstyles.formLabel}>О себе</label>
          <textarea className={mstyles.formTextarea} value={about}
                    onChange={(e) => setAbout(e.target.value)} rows={3} />
        </div>
        <div className={mstyles.formRow}>
          <label className={mstyles.formLabel}>Цвет аватара</label>
          <div className={pstyles.colorRow}>
            {AVATAR_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className={`${pstyles.swatch} ${color === c ? pstyles.swatchActive : ""}`}
                style={{ background: c }}
                onClick={() => setColor(c)}
                aria-label={c}
              />
            ))}
          </div>
        </div>

        <div className={mstyles.modalFooter}>
          <button className={mstyles.btnCancel} onClick={onClose}>Отмена</button>
          <button className={mstyles.btnSave} onClick={handleSave} disabled={saving}>
            {saving ? "Сохранение…" : "Сохранить"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
