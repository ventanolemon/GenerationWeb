// Запись из браузера → WAV, который умеет читать ядро.
//
// Зачем это здесь, а не на сервере
// --------------------------------
// `MediaRecorder` отдаёт webm с opus внутри, а проверка произношения
// читает PCM WAV (`core/pronunciation_match.read_wav`) и сжатых форматов
// не понимает НАМЕРЕННО: их разбор потребовал бы внешней библиотеки, а с
// ней — зависимости, которой у автономной установки может не быть.
//
// Значит, кто-то должен раскодировать opus. Сервер для этого пришлось бы
// снабдить кодеком (ffmpeg в образе), а у браузера декодер уже есть —
// Web Audio раскодирует что угодно, что умеет воспроизводить. Работа
// делается там, где инструмент уже лежит.
//
// Что здесь НЕ делается: сжатие, шумоподавление, нормализация громкости.
// Громкость проверке безразлична (нулевой кепстральный коэффициент
// отбрасывается), а остальное изменило бы запись до того, как её увидит
// правило, — и объяснить вердикт стало бы нечем.

/** Частота, к которой ядро приводит любой сигнал (`TARGET_RATE`). */
export const TARGET_RATE = 11025;

/** Приставка встроенной записи. Ровно то, что ждёт `core/answers.py`. */
export const INLINE_PREFIX = "data:audio/wav;base64,";

/**
 * Свести каналы в моно.
 *
 * Тем же средним, что и ядро (`read_wav`): стерео с микрофона обычно
 * одинаково в обоих каналах, но если различие есть, выбор одного канала
 * зависел бы от того, какой из них выбрали, — а среднее не зависит.
 */
export function toMono(channels: Float32Array[]): Float32Array {
  if (channels.length === 0) return new Float32Array(0);
  if (channels.length === 1) return channels[0];
  const length = channels[0].length;
  const out = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    let sum = 0;
    for (const channel of channels) sum += channel[i] ?? 0;
    out[i] = sum / channels.length;
  }
  return out;
}

/**
 * Линейная передискретизация — та же, что в ядре (`resample`).
 *
 * Совпадение не косметическое. Приводить частоту всё равно придётся, и
 * если бы браузер делал это одним способом, а приложение другим, одна и
 * та же запись давала бы чуть разные признаки на двух клиентах. Разница
 * мала, но правило приёма сравнивает РАССТОЯНИЯ, и объяснять расхождение
 * вердиктов пришлось бы уже на живом ответе студента.
 *
 * Приводим здесь, а не на сервере, по второй причине: 48 кГц весят вчетверо
 * больше 11 025, а разница едет по сети внутри поля ответа.
 */
export function resample(
  signal: Float32Array,
  sourceRate: number,
  targetRate: number = TARGET_RATE,
): Float32Array {
  if (sourceRate === targetRate || signal.length === 0) return signal;
  const count = Math.round((signal.length * targetRate) / sourceRate);
  if (count <= 1) return signal;
  const out = new Float32Array(count);
  // Концы отрезка совмещаются — так же, как np.linspace(0, 1, n) с обеих
  // сторон в ядре.
  const step = (signal.length - 1) / (count - 1);
  for (let i = 0; i < count; i += 1) {
    const at = i * step;
    const left = Math.floor(at);
    const right = Math.min(left + 1, signal.length - 1);
    const frac = at - left;
    out[i] = signal[left] * (1 - frac) + signal[right] * frac;
  }
  return out;
}

/**
 * Моно-сигнал → байты WAV (PCM, 16 бит).
 *
 * Разрядность именно 16: `read_wav` понимает 8, 16 и 32, но восемь бит
 * теряют динамику тихой речи, а тридцать два вдвое утяжеляют ответ, не
 * добавляя ничего, что различит правило.
 */
export function encodeWav(
  signal: Float32Array,
  rate: number = TARGET_RATE,
): Uint8Array {
  const bytes = new Uint8Array(44 + signal.length * 2);
  const view = new DataView(bytes.buffer);
  const ascii = (at: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(at + i, text.charCodeAt(i));
  };

  ascii(0, "RIFF");
  view.setUint32(4, 36 + signal.length * 2, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true);           // длина блока fmt
  view.setUint16(20, 1, true);            // 1 = PCM без сжатия
  view.setUint16(22, 1, true);            // каналов
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);     // байт в секунду
  view.setUint16(32, 2, true);            // байт на кадр
  view.setUint16(34, 16, true);           // бит на отсчёт
  ascii(36, "data");
  view.setUint32(40, signal.length * 2, true);

  for (let i = 0; i < signal.length; i += 1) {
    // Ограничение обязательно: значение вне [-1, 1] переполнило бы
    // int16 и превратилось бы в щелчок противоположного знака.
    const value = Math.max(-1, Math.min(1, signal[i]));
    view.setInt16(44 + i * 2, Math.round(value * 32767), true);
  }
  return bytes;
}

/** Байты → `data:audio/wav;base64,…` — форма ответа, понятная ядру. */
export function toInlineAnswer(wav: Uint8Array): string {
  let binary = "";
  // Кусками: `String.fromCharCode(...массив)` на длинной записи упирается
  // в предел числа аргументов и падает — на короткой при этом работает,
  // то есть ломалось бы ровно на длинных ответах.
  const CHUNK = 0x8000;
  for (let at = 0; at < wav.length; at += CHUNK) {
    binary += String.fromCharCode(...wav.subarray(at, at + CHUNK));
  }
  return INLINE_PREFIX + btoa(binary);
}

/**
 * Всё вместе: раскодированная запись → значение ответа.
 *
 * Принимается не `AudioBuffer`, а его содержимое: так функция остаётся
 * чистой и проверяемой без браузера. Web Audio трогает только вызывающий.
 */
export function answerFromChannels(
  channels: Float32Array[],
  sampleRate: number,
): string {
  const mono = resample(toMono(channels), sampleRate);
  return toInlineAnswer(encodeWav(mono));
}
