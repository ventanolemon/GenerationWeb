import type { Partition } from "../api/types";
import styles from "../styles/sidebar.module.css";

interface Props {
  partitions: Partition[];
  selectedId: number | null;
  onSelect: (p: Partition) => void;
}

export default function PartitionList({ partitions, selectedId, onSelect }: Props) {
  if (partitions.length === 0) {
    return <div className={styles.empty}>Разделы не найдены</div>;
  }
  return (
    <ul className={styles.partitionList}>
      {partitions.map((p) => {
        const disabled = !p.has_generator;
        const isSelected = p.id === selectedId;
        const cls = [
          styles.partitionItem,
          disabled ? styles.partitionDisabled : "",
          isSelected ? styles.partitionSelected : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <li
            key={p.id}
            className={cls}
            title={disabled ? "Генератор не зарегистрирован" : ""}
            onClick={() => {
              if (!disabled) onSelect(p);
            }}
          >
            {p.name}
          </li>
        );
      })}
    </ul>
  );
}
