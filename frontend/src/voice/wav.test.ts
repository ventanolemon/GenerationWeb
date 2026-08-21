import { describe, expect, it } from "vitest";
import {
  INLINE_PREFIX, TARGET_RATE, answerFromChannels, encodeWav, resample, toMono,
  toInlineAnswer,
} from "./wav";

/**
 * Разбор WAV — обратная сторона `encodeWav`, ровно то, что делает ядро.
 *
 * Написана здесь, а не взята готовой, по той же причине, по какой сам
 * кодировщик написан руками: проверять надо БАЙТЫ, которые уедут на
 * сервер, а не то, что о них думает библиотека.
 */
function parseWav(bytes: Uint8Array) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const tag = (at: number) =>
    String.fromCharCode(...Array.from(bytes.subarray(at, at + 4)));
  const samples = new Float32Array((view.getUint32(40, true)) / 2);
  for (let i = 0; i < samples.length; i += 1) {
    samples[i] = view.getInt16(44 + i * 2, true) / 32767;
  }
  return {
    riff: tag(0),
    wave: tag(8),
    format: view.getUint16(20, true),
    channels: view.getUint16(22, true),
    rate: view.getUint32(24, true),
    bits: view.getUint16(34, true),
    dataTag: tag(36),
    samples,
  };
}

describe("сведение каналов", () => {
  it("СРЕДНИМ, А НЕ ВЫБОРОМ ОДНОГО", () => {
    // Выбор канала зависел бы от того, какой выбрали; среднее — нет.
    const left = new Float32Array([1, 0, -1]);
    const right = new Float32Array([0, 0, 1]);
    expect(Array.from(toMono([left, right]))).toEqual([0.5, 0, 0]);
  });

  it("моно отдаёт как есть", () => {
    const only = new Float32Array([0.25, -0.25]);
    expect(toMono([only])).toBe(only);
  });

  it("пустой список не роняет", () => {
    expect(toMono([]).length).toBe(0);
  });
});

describe("передискретизация", () => {
  it("ДЕЛАЕТ ТО ЖЕ, ЧТО ЯДРО", () => {
    // Совпадение с `core.pronunciation_match.resample` не косметика:
    // разойдись они — одна и та же запись давала бы разные признаки в
    // браузере и в приложении, а правило сравнивает расстояния.
    //
    // Ожидаемое взято ПРОГОНОМ ядра, а не выведено в уме, и первая
    // редакция этой проверки как раз показала, зачем: «удвоение частоты
    // даёт три отсчёта» звучит убедительно и неверно. Отсчётов четыре
    // (round(2 × 200/100)), и концы совмещены — [0, ⅓, ⅔, 1].
    //
    //     >>> resample(np.array([0., 1.]), 100, 200)
    //     [0.0, 0.33333334, 0.6666667, 1.0]
    const doubled = Array.from(resample(new Float32Array([0, 1]), 100, 200));
    expect(doubled.length).toBe(4);
    [0, 1 / 3, 2 / 3, 1].forEach((want, i) => {
      expect(Math.abs(doubled[i] - want)).toBeLessThan(1e-6);
    });

    //     >>> resample(np.array([0., 1., 0., -1.]), 100, 250)
    //     [0.0, 0.33333334, …, -1.0]   — десять отсчётов
    const stretched = Array.from(
      resample(new Float32Array([0, 1, 0, -1]), 100, 250));
    const expected = [0, 1 / 3, 2 / 3, 1, 2 / 3, 1 / 3, 0, -1 / 3, -2 / 3, -1];
    expect(stretched.length).toBe(expected.length);
    expected.forEach((want, i) => {
      expect(Math.abs(stretched[i] - want)).toBeLessThan(1e-6);
    });
  });

  it("на равных частотах не трогает сигнал", () => {
    const signal = new Float32Array([0.1, 0.2]);
    expect(resample(signal, TARGET_RATE, TARGET_RATE)).toBe(signal);
  });

  it("сжимает 48 кГц к целевой частоте", () => {
    const signal = new Float32Array(48000);
    expect(resample(signal, 48000).length).toBe(TARGET_RATE);
  });

  it("не роняет пустую запись", () => {
    expect(resample(new Float32Array(0), 48000).length).toBe(0);
  });
});

describe("заголовок WAV", () => {
  it("ОБЪЯВЛЯЕТ ИМЕННО ТО, ЧТО УМЕЕТ ЧИТАТЬ ЯДРО", () => {
    // `read_wav` понимает несжатый PCM 8/16/32 бит. Здесь 16 и моно —
    // и это должно быть видно в байтах, а не в намерении.
    const parsed = parseWav(encodeWav(new Float32Array([0, 0.5]), TARGET_RATE));
    expect(parsed.riff).toBe("RIFF");
    expect(parsed.wave).toBe("WAVE");
    expect(parsed.dataTag).toBe("data");
    expect(parsed.format).toBe(1);
    expect(parsed.channels).toBe(1);
    expect(parsed.bits).toBe(16);
    expect(parsed.rate).toBe(TARGET_RATE);
  });

  it("длина данных сходится с числом отсчётов", () => {
    const bytes = encodeWav(new Float32Array(1000));
    expect(bytes.length).toBe(44 + 2000);
    expect(parseWav(bytes).samples.length).toBe(1000);
  });
});

describe("отсчёты", () => {
  it("переживают кодирование без заметной потери", () => {
    const signal = new Float32Array(64);
    for (let i = 0; i < signal.length; i += 1) {
      signal[i] = Math.sin((i / signal.length) * Math.PI * 2);
    }
    const back = parseWav(encodeWav(signal)).samples;
    for (let i = 0; i < signal.length; i += 1) {
      expect(Math.abs(back[i] - signal[i])).toBeLessThan
        ? expect(Math.abs(back[i] - signal[i])).toBeLessThan(1e-4)
        : undefined;
    }
  });

  it("ЗАШКАЛ ОБРЕЗАЕТСЯ, А НЕ ПЕРЕПОЛНЯЕТСЯ", () => {
    // Значение вне [-1, 1] без ограничения переполнило бы int16 и стало
    // бы щелчком ПРОТИВОПОЛОЖНОГО знака — то есть громкая запись
    // превращалась бы в треск.
    const back = parseWav(encodeWav(new Float32Array([2, -2]))).samples;
    expect(back[0]).toBeGreaterThan(0.99);
    expect(back[1]).toBeLessThan(-0.99);
  });
});

describe("значение ответа", () => {
  it("НАЧИНАЕТСЯ С ПРИСТАВКИ, КОТОРУЮ ЖДЁТ ЯДРО", () => {
    // Приставка объявлена в `core/answers.py` (INLINE_PREFIX). Разойдись
    // строки — сервер принял бы запись за путь к файлу и ответил
    // «записи нет», не сказав про формат ни слова.
    expect(INLINE_PREFIX).toBe("data:audio/wav;base64,");
    const answer = answerFromChannels([new Float32Array([0, 0.5])], TARGET_RATE);
    expect(answer.startsWith(INLINE_PREFIX)).toBe(true);
  });

  it("раскодируется обратно в те же байты", () => {
    const wav = encodeWav(new Float32Array([0.5, -0.5]));
    const base64 = toInlineAnswer(wav).slice(INLINE_PREFIX.length);
    const back = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
    expect(Array.from(back)).toEqual(Array.from(wav));
  });

  it("ДЛИННАЯ ЗАПИСЬ НЕ РОНЯЕТ КОДИРОВАНИЕ", () => {
    // `String.fromCharCode(...массив)` на длинном массиве упирается в
    // предел числа аргументов. Сломалось бы это только на длинных
    // ответах — то есть у того, кто говорил дольше других.
    const long = answerFromChannels(
      [new Float32Array(TARGET_RATE * 20)], TARGET_RATE);
    expect(long.length).toBeGreaterThan(100000);
    expect(long.startsWith(INLINE_PREFIX)).toBe(true);
  });

  it("приводит частоту, чтобы ответ не вырос вчетверо", () => {
    const at48 = answerFromChannels([new Float32Array(48000)], 48000);
    const at11 = answerFromChannels([new Float32Array(TARGET_RATE)], TARGET_RATE);
    // Секунда записи весит одинаково, с какой бы частоты ни пришла.
    expect(Math.abs(at48.length - at11.length)).toBeLessThan(64);
  });
});
