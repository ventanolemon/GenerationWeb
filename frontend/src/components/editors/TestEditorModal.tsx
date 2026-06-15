import { useEffect, useState } from "react";
import type { Partition } from "../../api/types";
import { api } from "../../api/client";
import Modal from "../Modal";
import mstyles from "../../styles/modal.module.css";

interface Props {
  subjectId: number;
  partitionId: number | null;
  onSaved: (newId: number) => void;
  onClose: () => void;
}

interface TestRow {
  partitionId: number;
  name: string;
  count: number;
}

/**
 * Редактор теста (constracted=3).
 * Тест — упорядоченный список заданий с указанием количества вариантов.
 * Кандидаты: разделы своего предмета + «дочерних» предметов (pra_subject = мой subject_name).
 */
export default function TestEditorModal({ subjectId, partitionId, onSaved, onClose }: Props) {
  const [name, setName] = useState("");
  const [candidates, setCandidates] = useState<Partition[]>([]);
  const [rows, setRows] = useState<TestRow[]>([]);
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [cands, existingPart] = await Promise.all([
          api.getPartitionCandidates(subjectId),
          partitionId ? api.getPartitionForEdit(partitionId) : Promise.resolve(null),
        ]);

        // В тест можно добавлять разделы своего предмета + родственных (siblings),
        // кроме других тестов и самого себя
        const all = [...cands.own, ...cands.siblings].filter(
          (p) => p.constracted !== 3 && p.id !== partitionId,
        );
        // Убираем дубликаты
        const seen = new Set<number>();
        const deduped = all.filter((p) => { if (seen.has(p.id)) return false; seen.add(p.id); return true; });
        setCandidates(deduped);
        if (deduped.length > 0) setSelectedCandidateId(deduped[0].id);

        if (existingPart) {
          setName(existingPart.name);
          const params = existingPart.generation_params as { data?: Array<{ task_id: number; task_name: string; task_cnt: number }> };
          const items = params?.data ?? [];
          setRows(items.map((x) => ({ partitionId: x.task_id, name: x.task_name, count: x.task_cnt ?? 1 })));
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [subjectId, partitionId]);

  function addRow() {
    if (!selectedCandidateId) return;
    const cand = candidates.find((c) => c.id === selectedCandidateId);
    if (!cand) return;
    setRows((prev) => [...prev, { partitionId: cand.id, name: cand.name, count: 1 }]);
  }

  function removeRow(idx: number) {
    setRows((prev) => prev.filter((_, i) => i !== idx));
  }

  function moveRow(idx: number, dir: -1 | 1) {
    const target = idx + dir;
    if (target < 0 || target >= rows.length) return;
    setRows((prev) => {
      const next = [...prev];
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  }

  function setCount(idx: number, val: string) {
    const n = Math.max(1, parseInt(val, 10) || 1);
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, count: n } : r)));
  }

  async function handleSave() {
    if (!name.trim()) { setError("Введите название теста."); return; }
    if (rows.length === 0) { setError("Добавьте хотя бы одно задание."); return; }

    const data = rows.map((r) => ({
      task_id: r.partitionId,
      task_name: r.name,
      task_cnt: r.count,
    }));

    setSaving(true);
    setError(null);
    try {
      const result = await api.upsertPartition({
        subject_id: subjectId,
        name: name.trim(),
        constracted: 3,
        generation_params: { parent_subject: subjectId, data },
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
      title={partitionId ? "Редактирование теста" : "Создание теста"}
      onClose={onClose}
      width={560}
    >
      {loading ? (
        <div>Загрузка…</div>
      ) : (
        <>
          {error && <div className={mstyles.errorMsg}>{error}</div>}
          <div className={mstyles.formRow}>
            <label className={mstyles.formLabel}>Название теста:</label>
            <input
              className={mstyles.formInput}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>

          <div className={mstyles.formRow}>
            <label className={mstyles.formLabel}>Тип задания:</label>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <select
                className={mstyles.formSelect}
                style={{ flex: 1 }}
                value={selectedCandidateId ?? ""}
                onChange={(e) => setSelectedCandidateId(Number(e.target.value))}
              >
                {candidates.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={addRow}
                style={{ padding: "0.4rem 0.9rem", background: "#4a7fd4", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}
              >
                Добавить
              </button>
            </div>
          </div>

          <div style={{ border: "1px solid #ddd", borderRadius: 4, marginBottom: "0.9rem", maxHeight: 260, overflowY: "auto" }}>
            {rows.length === 0 && (
              <div style={{ padding: "0.6rem", color: "#888", fontStyle: "italic" }}>Нет заданий</div>
            )}
            {rows.map((row, idx) => (
              <div
                key={idx}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.5rem",
                  padding: "0.35rem 0.6rem",
                  borderBottom: "1px solid #f0f0f0",
                }}
              >
                <span style={{ flex: 1, fontSize: "0.9rem" }}>{row.name}</span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={row.count}
                  onChange={(e) => setCount(idx, e.target.value)}
                  style={{ width: 52, textAlign: "center", padding: "0.2rem", border: "1px solid #bbb", borderRadius: 3 }}
                />
                <button onClick={() => moveRow(idx, -1)} disabled={idx === 0} style={{ border: "1px solid #ccc", background: "#fff", borderRadius: 3, width: 26, cursor: "pointer" }}>↑</button>
                <button onClick={() => moveRow(idx, 1)} disabled={idx === rows.length - 1} style={{ border: "1px solid #ccc", background: "#fff", borderRadius: 3, width: 26, cursor: "pointer" }}>↓</button>
                <button onClick={() => removeRow(idx)} style={{ border: "1px solid #d99", background: "#fff", color: "#c33", borderRadius: 3, width: 26, cursor: "pointer" }}>×</button>
              </div>
            ))}
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
