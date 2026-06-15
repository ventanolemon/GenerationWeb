import { useEffect, useState } from "react";
import type { Partition, PartitionEditData } from "../../api/types";
import { api } from "../../api/client";
import Modal from "../Modal";
import mstyles from "../../styles/modal.module.css";

interface Props {
  subjectId: number;
  partitionId: number | null; // null — создание, число — редактирование
  onSaved: (newId: number) => void;
  onClose: () => void;
}

/**
 * Редактор группы (constracted=2).
 * Группа — это набор разделов того же предмета (кроме других групп).
 */
export default function GroupEditorModal({ subjectId, partitionId, onSaved, onClose }: Props) {
  const [name, setName] = useState("");
  const [candidates, setCandidates] = useState<Partition[]>([]);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let existing: PartitionEditData | null = null;

    async function load() {
      setLoading(true);
      try {
        const [cands, existingPart] = await Promise.all([
          api.getPartitionCandidates(subjectId),
          partitionId ? api.getPartitionForEdit(partitionId) : Promise.resolve(null),
        ]);
        existing = existingPart;

        // Кандидаты — только из своего предмета, без других групп (constracted != 2)
        // и не себя самого при редактировании
        const filtered = cands.own.filter(
          (p) => p.constracted !== 2 && p.id !== partitionId,
        );
        setCandidates(filtered);

        if (existing) {
          setName(existing.name);
          const params = existing.generation_params as { data?: Array<{ task_id: number }> } | Array<{ task_id: number }>;
          const items: Array<{ task_id: number }> = Array.isArray(params)
            ? params
            : (params as { data?: Array<{ task_id: number }> }).data ?? [];
          setChecked(new Set(items.map((x) => x.task_id)));
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [subjectId, partitionId]);

  function toggle(id: number) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleSave() {
    if (!name.trim()) { setError("Введите название группы."); return; }
    if (checked.size === 0) { setError("Выберите хотя бы один раздел."); return; }

    const data = candidates
      .filter((p) => checked.has(p.id))
      .map((p) => ({ task_id: p.id, task_name: p.name, constracted: p.constracted }));

    setSaving(true);
    setError(null);
    try {
      const result = await api.upsertPartition({
        subject_id: subjectId,
        name: name.trim(),
        constracted: 2,
        generation_params: data,
      });
      onSaved(result.partition_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={partitionId ? "Редактирование группы" : "Создание группы"}
      onClose={onClose}
      width={460}
    >
      {loading ? (
        <div>Загрузка…</div>
      ) : (
        <>
          {error && <div className={mstyles.errorMsg}>{error}</div>}
          <div className={mstyles.formRow}>
            <label className={mstyles.formLabel}>Название группы:</label>
            <input
              className={mstyles.formInput}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>
          <div className={mstyles.formRow}>
            <label className={mstyles.formLabel}>Содержит разделы:</label>
            <div style={{ border: "1px solid #ddd", borderRadius: 4, maxHeight: 280, overflowY: "auto" }}>
              {candidates.length === 0 && (
                <div style={{ padding: "0.6rem", color: "#888", fontStyle: "italic" }}>
                  Нет доступных разделов
                </div>
              )}
              {candidates.map((p) => (
                <label
                  key={p.id}
                  style={{
                    display: "flex",
                    gap: "0.5rem",
                    alignItems: "center",
                    padding: "0.35rem 0.7rem",
                    cursor: "pointer",
                    borderBottom: "1px solid #f0f0f0",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={checked.has(p.id)}
                    onChange={() => toggle(p.id)}
                  />
                  {p.name}
                </label>
              ))}
            </div>
          </div>
          <div className={mstyles.modalFooter}>
            <button className={mstyles.btnCancel} onClick={onClose}>Отмена</button>
            <button className={mstyles.btnSave} onClick={handleSave} disabled={saving}>
              {saving ? "Сохранение…" : "Сохранить"}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
