import { useEffect, useRef, useState } from "react";
import type { Subject } from "../api/types";
import styles from "../styles/sidebar.module.css";

interface Props {
  subjects: Subject[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export default function SubjectPicker({ subjects, selectedId, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const selected = subjects.find((s) => s.id === selectedId) ?? null;

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div className={styles.subjectPicker} ref={ref}>
      <label className={styles.label}>Предмет:</label>
      <button
        type="button"
        className={`${styles.dropdownTrigger} ${open ? styles.dropdownTriggerOpen : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className={styles.dropdownValue}>
          {selected ? selected.name : "— выберите —"}
        </span>
        <span className={styles.dropdownChevron} aria-hidden>▾</span>
      </button>

      {open && (
        <ul className={styles.dropdownMenu} role="listbox">
          {subjects.map((s) => (
            <li
              key={s.id}
              role="option"
              aria-selected={s.id === selectedId}
              className={`${styles.dropdownOption} ${s.id === selectedId ? styles.dropdownOptionSelected : ""}`}
              onMouseDown={() => { onSelect(s.id); setOpen(false); }}
            >
              {s.name}
            </li>
          ))}
          {subjects.length === 0 && (
            <li className={styles.dropdownEmpty}>Нет предметов</li>
          )}
        </ul>
      )}
    </div>
  );
}
