import type { Subject } from "../api/types";
import styles from "../styles/sidebar.module.css";

interface Props {
  subjects: Subject[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export default function SubjectPicker({ subjects, selectedId, onSelect }: Props) {
  return (
    <div className={styles.subjectPicker}>
      <label className={styles.label}>Предмет:</label>
      <select
        className={styles.select}
        value={selectedId ?? ""}
        onChange={(e) => onSelect(Number(e.target.value))}
      >
        {selectedId === null && <option value="">— выберите —</option>}
        {subjects.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
    </div>
  );
}
