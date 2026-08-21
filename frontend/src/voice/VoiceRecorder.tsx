// Запись голоса в браузере — веб-половина задания на произношение.
//
// Ответом уезжает САМА ЗАПИСЬ (`data:audio/wav;base64,…`), а не путь к
// файлу: путь назвал бы файл на машине студента, и сервер, приняв его,
// прочитал бы что-то своё. Форма ответа описана в `core/answers.py`
// (`_recording_source`), кодирование — в `./wav.ts`.
//
// Проверяет запись ТА ЖЕ спецификация, что на десктопе, тем же правилом
// окрестности. Это и было целью: не «веб-версия проверки», а один и тот
// же вердикт на двух клиентах.
//
// Чего здесь нет: хранения. Запись живёт в памяти вкладки до ответа и
// уходит вместе с ним; в попытку идёт вердикт, а не голос.

import { useEffect, useRef, useState } from "react";
import styles from "../styles/views.module.css";
import { answerFromChannels } from "./wav";

interface Props {
  /** Подсказка задания — обычно транскрипция. */
  hint?: string;
  disabled?: boolean;
  /** Сменился вопрос — забыть запись. */
  resetKey?: number;
  /** Готовое значение ответа или пустая строка, если записи нет. */
  onRecorded(answer: string): void;
}

type Stage = "idle" | "recording" | "decoding" | "ready" | "failed";

const IDLE_HINT = "Нажмите «Записать» и произнесите слово.";

/**
 * Есть ли в этом браузере чем записывать.
 *
 * Проверяется ДО первой кнопки, чтобы не предлагать действие, которое
 * заведомо не состоится. `getUserMedia` живёт только в защищённом
 * контексте (https или localhost), и по http его в объекте просто нет —
 * это самая частая причина отсутствия записи, и сказать о ней надо
 * словами, а не пустой кнопкой.
 */
export function recordingSupport(): { ok: boolean; reason: string } {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    const insecure =
      typeof window !== "undefined" && window.isSecureContext === false;
    return {
      ok: false,
      reason: insecure
        ? "Запись доступна только по защищённому соединению (https)."
        : "Браузер не даёт доступ к микрофону.",
    };
  }
  if (typeof MediaRecorder === "undefined") {
    return { ok: false, reason: "Браузер не умеет записывать звук." };
  }
  return { ok: true, reason: "" };
}

export default function VoiceRecorder({
  hint, disabled, resetKey, onRecorded,
}: Props) {
  const support = recordingSupport();
  const [stage, setStage] = useState<Stage>("idle");
  const [message, setMessage] = useState(support.ok ? IDLE_HINT : support.reason);
  const [preview, setPreview] = useState<string>("");

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  // Микрофон обязан гаснуть вместе с компонентом. Оставленная дорожка —
  // это горящий индикатор записи у студента, который уже ушёл со
  // страницы; браузер её сам не отпустит.
  function release() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }
  useEffect(() => release, []);

  // Смена вопроса: прошлая запись не должна уехать ответом на следующий.
  useEffect(() => {
    setPreview("");
    onRecorded("");
    if (stage !== "recording") {
      setStage(support.ok ? "idle" : "failed");
      setMessage(support.ok ? IDLE_HINT : support.reason);
    }
    // Намеренно только по resetKey: перезапуск на каждое изменение
    // `onRecorded` стирал бы запись прямо под студентом.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  async function start() {
    setPreview("");
    onRecorded("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => void finish();
      recorder.start();
      setStage("recording");
      setMessage("Идёт запись…");
    } catch (error) {
      release();
      setStage("failed");
      // Отказ в доступе и отсутствие устройства — разные вещи, и
      // студенту от «не получилось» пользы нет: в первом случае надо
      // разрешить доступ, во втором — подключить микрофон.
      const name = (error as { name?: string })?.name ?? "";
      setMessage(
        name === "NotAllowedError"
          ? "Доступ к микрофону запрещён. Разрешите его в настройках сайта."
          : name === "NotFoundError"
            ? "Микрофон не найден."
            : "Не удалось начать запись.",
      );
    }
  }

  async function finish() {
    const blob = new Blob(chunksRef.current, {
      type: recorderRef.current?.mimeType || "audio/webm",
    });
    release();
    chunksRef.current = [];
    if (blob.size === 0) {
      setStage("failed");
      setMessage("Запись пуста — попробуйте ещё раз.");
      return;
    }
    setStage("decoding");
    setMessage("Обработка…");
    try {
      // Раскодирование делает сам браузер: у него декодер opus уже есть,
      // а ядро сжатых форматов не читает намеренно (см. `./wav.ts`).
      const context = new (window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext)();
      const decoded = await context.decodeAudioData(await blob.arrayBuffer());
      const channels: Float32Array[] = [];
      for (let i = 0; i < decoded.numberOfChannels; i += 1) {
        channels.push(decoded.getChannelData(i));
      }
      const answer = answerFromChannels(channels, decoded.sampleRate);
      void context.close();

      setPreview(answer);
      onRecorded(answer);
      setStage("ready");
      setMessage(`Записано, ${decoded.duration.toFixed(1)} с. Можно прослушать.`);
    } catch {
      setStage("failed");
      setMessage("Запись не удалось обработать — попробуйте ещё раз.");
    }
  }

  function stop() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  const busy = disabled || stage === "decoding";
  return (
    <div className={styles.voiceRecorder}>
      <div className={styles.voiceRow}>
        <button
          type="button"
          className={styles.voiceButton}
          onClick={stage === "recording" ? stop : start}
          disabled={busy || !support.ok}
          title={support.ok ? undefined : support.reason}
        >
          {stage === "recording" ? "■ Стоп" : "● Записать"}
        </button>
        <span className={styles.voiceStatus}>{message}</span>
      </div>
      {hint ? <div className={styles.answerHint}>{hint}</div> : null}
      {preview ? (
        // Прослушать своё — не украшение: без этого «неверно» неотличимо
        // от «микрофон записал тишину», и студент чинит произношение там,
        // где сломан звук.
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <audio className={styles.voicePreview} controls src={preview} />
      ) : null}
    </div>
  );
}
