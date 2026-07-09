import { useRef, useState } from "react";
import type { Partition } from "../api/types";
import { api } from "../api/client";
import GroupEditorModal from "./editors/GroupEditorModal";
import TestEditorModal from "./editors/TestEditorModal";
import FisicEditorModal from "./editors/FisicEditorModal";
import GraphEditorModal from "../graph-editor/GraphEditorModal";
import styles from "../styles/sidebar.module.css";

interface Props {
  subjectId: number | null;
  selected: Partition | null;
  onChanged: () => void; // перезагрузить список разделов
}

type EditorKind = "group" | "test" | "fisic" | "graph";
type OpenEditor =
  | { kind: EditorKind; partitionId: number | null }
  | null;

/**
 * Панель под списком разделов: кнопки «+ Создать», «Изменить», «Удалить».
 * Логика совпадает с GeneratorWindow._build_partition_controls() из десктопа.
 *
 * constracted: 0=code-only (нет редактора), 1=fisic, 2=group, 3=test, 4=graph
 */
export default function PartitionControls({ subjectId, selected, onChanged }: Props) {
  const [open, setOpen] = useState<OpenEditor>(null);
  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const createBtnRef = useRef<HTMLButtonElement | null>(null);

  const editorKind: EditorKind | null =
    selected?.constracted === 1 ? "fisic"
    : selected?.constracted === 2 ? "group"
    : selected?.constracted === 3 ? "test"
    : selected?.constracted === 4 ? "graph"
    : null;

  const canEdit = editorKind !== null;

  function openCreate(kind: EditorKind) {
    setCreateMenuOpen(false);
    setOpen({ kind, partitionId: null });
  }

  function openEdit() {
    if (!selected || !editorKind) return;
    setOpen({ kind: editorKind, partitionId: selected.id });
  }

  async function handleDelete() {
    if (!selected) return;
    try {
      await api.deletePartition(selected.id, selected.subject_id);
      setConfirmDelete(false);
      onChanged();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    }
  }

  function handleSaved() {
    setOpen(null);
    onChanged();
  }

  if (!subjectId) return null;

  return (
    <>
      <div className={styles.partitionControls}>
        {/* + Создать — выпадающее меню */}
        <div className={styles.createWrap}>
          <button
            ref={createBtnRef}
            className={styles.ctrlBtn}
            onClick={() => setCreateMenuOpen((v) => !v)}
          >
            + Создать ▾
          </button>
          {createMenuOpen && (
            <div className={styles.createMenu}>
              <button onClick={() => openCreate("group")}>Группу</button>
              <button onClick={() => openCreate("test")}>Тест</button>
              <button onClick={() => openCreate("fisic")}>Задачу по физике</button>
              <button onClick={() => openCreate("graph")}>Граф</button>
            </div>
          )}
        </div>

        <button
          className={styles.ctrlBtn}
          disabled={!canEdit}
          onClick={openEdit}
        >
          Изменить
        </button>

        <button
          className={`${styles.ctrlBtn} ${styles.ctrlBtnDanger}`}
          disabled={!canEdit}
          onClick={() => setConfirmDelete(true)}
        >
          Удалить
        </button>
      </div>

      {/* Подтверждение удаления */}
      {confirmDelete && selected && (
        <div className={styles.confirmBubble}>
          <span>Удалить «{selected.name}»?</span>
          <button onClick={handleDelete}>Да</button>
          <button onClick={() => setConfirmDelete(false)}>Нет</button>
        </div>
      )}

      {/* Редакторы */}
      {open?.kind === "group" && (
        <GroupEditorModal
          subjectId={subjectId}
          partitionId={open.partitionId}
          onSaved={handleSaved}
          onClose={() => setOpen(null)}
        />
      )}
      {open?.kind === "test" && (
        <TestEditorModal
          subjectId={subjectId}
          partitionId={open.partitionId}
          onSaved={handleSaved}
          onClose={() => setOpen(null)}
        />
      )}
      {open?.kind === "fisic" && (
        <FisicEditorModal
          subjectId={subjectId}
          partitionId={open.partitionId}
          onSaved={handleSaved}
          onClose={() => setOpen(null)}
        />
      )}
      {open?.kind === "graph" && (
        <GraphEditorModal
          subjectId={subjectId}
          partitionId={open.partitionId}
          onSaved={handleSaved}
          onClose={() => setOpen(null)}
        />
      )}
    </>
  );
}
