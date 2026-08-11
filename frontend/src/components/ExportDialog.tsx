import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { AnswerPlacement } from "../api/types";
import Modal from "./Modal";
import mstyles from "../styles/modal.module.css";

/**
 * Настройки выгрузки в .docx.
 *
 * Раньше настройка была одна — галочка «с ответами», и ответ всегда падал
 * ПОД задание. Такой лист нельзя раздать студентам: ключ на виду. Отсюда
 * четыре размещения, и это ровно те четыре, что были в проекте до
 * переработки.
 *
 * Вариант — тоже не украшение: «пять заданий с разрывом страницы» и «пять
 * вариантов» — разные вещи. У варианта есть номер, и ответы к нему
 * собираются вместе.
 */
const PLACEMENTS: { key: AnswerPlacement; label: string; hint: string }[] = [
  {
    key: "under",
    label: "Под заданием",
    hint: "Удобно себе для проверки; раздавать такой лист нельзя",
  },
  {
    key: "variant_end",
    label: "В конце варианта",
    hint: "Ключ к каждому варианту отдельной страницей — можно оторвать",
  },
  {
    key: "file_end",
    label: "В конце файла",
    hint: "Все ответы одной пачкой в конце, с указанием варианта",
  },
  {
    key: "hidden",
    label: "Не печатать",
    hint: "Только условия — лист для студентов",
  },
];

export default function ExportDialog({
  partitionId,
  partitionName,
  defaultCount = 1,
  onClose,
}: {
  partitionId: number;
  partitionName: string;
  defaultCount?: number;
  onClose: () => void;
}) {
  const [count, setCount] = useState(defaultCount);
  const [variants, setVariants] = useState(1);
  const [answers, setAnswers] = useState<AnswerPlacement>("under");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const blob = await api.export({
        partitionId,
        count,
        variants,
        answers,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${partitionName}.docx`;
      a.click();
      URL.revokeObjectURL(url);
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const total = count * variants;

  return (
    <Modal title="Экспорт в Word" onClose={onClose}>
      <div className={mstyles.body}>
        <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
          <label className={mstyles.formLabel} style={{ flex: 1 }}>
            Заданий в варианте
            <input
              className={mstyles.formInput}
              type="number"
              min={1}
              max={50}
              value={count}
              onChange={(e) => setCount(Math.max(1, Number(e.target.value)))}
            />
          </label>
          <label className={mstyles.formLabel} style={{ flex: 1 }}>
            Вариантов
            <input
              className={mstyles.formInput}
              type="number"
              min={1}
              max={50}
              value={variants}
              onChange={(e) => setVariants(Math.max(1, Number(e.target.value)))}
            />
          </label>
        </div>

        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend style={{ marginBottom: 8 }}>Ответы</legend>
          {PLACEMENTS.map((p) => (
            <label
              key={p.key}
              style={{
                display: "block",
                marginBottom: 8,
                cursor: "pointer",
              }}
            >
              <input
                type="radio"
                name="answers"
                checked={answers === p.key}
                onChange={() => setAnswers(p.key)}
              />{" "}
              <b>{p.label}</b>
              <div style={{ marginLeft: 24, opacity: 0.7, fontSize: "0.9em" }}>
                {p.hint}
              </div>
            </label>
          ))}
        </fieldset>

        <p style={{ opacity: 0.7, marginTop: 12 }}>
          Всего заданий в файле: <b>{total}</b>
          {variants > 1 && " — каждый вариант с новой страницы"}
        </p>

        {error && <div className={mstyles.errorMsg}>{error}</div>}
      </div>

      <div className={mstyles.modalFooter}>
        <button type="button" onClick={onClose} disabled={busy}>
          Отмена
        </button>
        <button className={mstyles.btnSave} type="button" onClick={submit} disabled={busy}>
          {busy ? "Собираем…" : "Скачать"}
        </button>
      </div>
    </Modal>
  );
}
