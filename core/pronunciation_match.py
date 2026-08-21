"""
Проверка произношения: ближайший эталон в СЛОВАРЕ, а не абсолютный порог.

Правило то же, что у опечатки
-----------------------------
`core/word_tolerance.py` установил: допуск на ошибку нельзя задавать
константой, он определяется окрестностью ответа в множестве допустимых.
Со звуком дело обстоит так же, и даже резче.

Абсолютный порог здесь плох по причине, которую можно назвать точно:
**его надо калибровать под голос и микрофон.** Расстояние до эталона
зависит от диктора и тракта записи сильнее, чем от того, верно ли
произнесено слово, — и порог, подобранный на одном голосе, на другом
приходится подбирать заново.

Оговорка о том, чего мы НЕ показали. Утверждение «междикторское
расстояние всегда превышает межсловное» известно из литературы, но
нашими данными не подтверждено: на поставочных эталонах с синтетическими
искажениями порог как раз разделял (18.2 против 21.0, см.
`test_absolute_threshold_is_not_ruled_out_on_this_material`). Живых
записей у нас нет, и опираться на это утверждение нельзя.

Правило ближайшего предпочтительно по проверяемой причине: **ему не
нужна калибровка.** Оно сравнивает запись с эталонами внутри одной
сессии, и общий сдвиг, вносимый голосом и микрофоном, на порядок
сравнения не влияет.

Правило:

    произношение принято, если эталон ЦЕЛЕВОГО слова оказался ближе
    к записи студента, чем эталоны других слов словаря.

Сравниваются не абсолютные величины, а порядок. Разница дикторов сдвигает
все расстояния разом и порядок не меняет — а именно порядок и несёт
смысл «студент сказал это слово, а не соседнее».

Что здесь есть и чего нет
-------------------------
Есть: признаки (MFCC), выравнивание по времени (DTW), правило выбора
ближайшего и мера уверенности. Всё на numpy, без внешних служб — иначе
сломалось бы требование автономной работы.

**Нет распознавания речи.** Модуль не переводит звук в текст и не
оценивает «правильность» произношения в фонетическом смысле. Он отвечает
на один вопрос: на какое слово словаря запись похожа больше всего. Для
словарного тренажёра этого достаточно, для постановки произношения —
нет, и притворяться иначе нельзя.

Уверенность меряется ТОЙ ЖЕ окрестностью
----------------------------------------
Мало выбрать ближайшего — надо ещё знать, отличим ли выбор от случайного.
Здесь была допущена ровно та ошибка, против которой написан весь модуль:
уверенность решалась КОНСТАНТОЙ (отрыв ≥ 8% от расстояния до ближайшего).

Замер по всем четырнадцати словарям поставки её опроверг: из 149
уверенных вердиктов 52 оказались неверными, причём разброс между
словарями огромен — на словаре длинных терминов ноль неверных, на
односложных до 13 из 21. Константа была подобрана под материал, на
котором её мерили, и на другой материал не перенеслась.

Правильная величина приносится САМИМ СЛОВАРЁМ:

    separation(W) = расстояние от эталона W до ближайшего ЧУЖОГО эталона

Идеальная запись слова W совпала бы с его эталоном: до своего 0, до
ближайшего чужого — ровно separation(W). Значит, отрыв, равный
separation(W), — это максимум достижимого, а отношение

    share = (расстояние до второго − расстояние до первого) / separation

отвечает на вопрос «какую часть возможного запись действительно взяла».
Величина безразмерна, лежит примерно в [0, 1] и НЕ ЗАВИСИТ от того,
насколько словарь плотен: на словаре из похожих слов достижимое
разделение мало, и требование автоматически становится строже.

Замер после замены (те же 14 словарей, окрестность 12 слов): **ноль
уверенно неверных вердиктов на всех словарях**, включая проверку на
половине словарей, не участвовавшей в подборе. Цена — покрытие; она
названа в `docs/thesis/07-chapter-results.md` §7.3.2.

Ограничение, которое надо знать
-------------------------------
Правило работает тем лучше, чем БОЛЬШЕ слов в словаре: при двух словах
случайное совпадение даёт 50%. При словаре из ОДНОГО слова уверенности
не бывает вовсе — сравнивать не с чем, и `confident` там ложь, а не
истина: отсутствие соперника это отсутствие свидетельства, а не
бесспорная победа.
"""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

import numpy as np

#: Частота, к которой приводится любой вход. Поставочные эталоны
#: синтезированы на 11025 Гц; приводить их вверх смысла нет.
TARGET_RATE = 11025

#: Окно анализа и шаг, в секундах. 25/10 мс — общепринятые значения для
#: речи: окно короче не ловит форманты, длиннее размывает переходы.
FRAME_SEC = 0.025
STEP_SEC = 0.010

#: Число мел-фильтров и оставляемых коэффициентов.
MEL_FILTERS = 26
CEPSTRA = 13

#: Какую долю ДОСТИЖИМОГО разделения обязана взять запись, чтобы вердикт
#: считался уверенным. Величина безразмерная и лежит примерно в [0, 1]:
#: единица — запись совпала с эталоном точно, ноль — легла ровно между
#: двумя словами. Смысл требования: «возьми хотя бы треть того, что на
#: этом словаре вообще можно взять».
#:
#: Это НЕ порог расстояния. Порог расстояния пришлось бы калибровать под
#: голос и микрофон; здесь калибровать нечего — масштаб приносит сам
#: словарь (см. `Match.separation`).
CONFIDENT_SHARE = 0.30


@dataclass(frozen=True)
class Match:
    """Результат сопоставления записи со словарём эталонов."""

    term: str
    """Слово, чей эталон оказался ближе всех."""

    distance: float
    """Расстояние до него."""

    runner_up: Optional[str]
    """Второе по близости слово; None — словарь из одного слова."""

    runner_up_distance: float
    """Расстояние до второго. inf, если его нет."""

    separation: float = float("inf")
    """
    Насколько эталон победителя отстоит от БЛИЖАЙШЕГО ЧУЖОГО эталона
    словаря. Масштаб, которым меряется отрыв.

    Это и есть окрестность, перенесённая на звук. Величина считается по
    одним эталонам и о записи ничего не знает — поэтому она не зависит
    ни от голоса, ни от микрофона, ни от уровня шума.

    inf — сравнивать не с чем (словарь из одного слова).
    """

    @property
    def gap(self) -> float:
        """Абсолютный отрыв ближайшего от следующего."""
        if not math.isfinite(self.runner_up_distance):
            return float("inf")
        return self.runner_up_distance - self.distance

    @property
    def share(self) -> float:
        """
        Доля достижимого разделения, которую взяла запись.

        Идеальная запись слова совпала бы с его эталоном: расстояние до
        своего 0, до ближайшего чужого — ровно `separation`, то есть
        отрыв равен `separation`, а доля равна единице. Реальная запись
        берёт меньше. Отсюда и смысл величины: **какую часть того, что на
        этом словаре вообще возможно, запись действительно взяла.**

        0 — сравнивать бессмысленно: либо разделения нет (эталоны
        неразличимы), либо словарь из одного слова, либо запись легла
        между двумя словами.
        """
        if not math.isfinite(self.separation) or self.separation <= 0:
            return 0.0
        if not math.isfinite(self.gap):
            return 0.0
        return self.gap / self.separation

    @property
    def confident(self) -> bool:
        return self.share >= CONFIDENT_SHARE

    @property
    def margin(self) -> float:
        """
        Отрыв, отнесённый к расстоянию до ближайшего. СПРАВОЧНАЯ величина.

        Раньше именно она решала, уверен ли вердикт, и порог был
        константой 0.08. Замер по всем словарям поставки этот порог
        опроверг: он подобран под материал, на котором его мерили, и на
        других словарях давал уверенно неверные вердикты — 52 из 149.
        Разбор в `docs/thesis/07-chapter-results.md` §7.3.1.

        Величина осталась потому, что она удобна для диагностики
        (сравнима между дикторами и не требует эталонных расстояний), но
        решения по ней больше не принимаются.
        """
        if not math.isfinite(self.runner_up_distance) or self.distance <= 0:
            return float("inf") if self.runner_up is None else 0.0
        return (self.runner_up_distance - self.distance) / self.distance


# ---------------------------------------------------------------- звук

def read_wav(path) -> tuple[np.ndarray, int]:
    """
    Прочитать WAV в моно-массив float32 в диапазоне [-1, 1].

    Поддерживается 8/16/32-битный PCM — то, что порождают синтезаторы и
    браузерная запись. Сжатые форматы не поддерживаются намеренно: их
    разбор потребовал бы внешней библиотеки, а с ней — зависимости,
    которой у автономной установки может не быть.

    Принимается путь ИЛИ открытый двоичный поток. Второе — ради веба:
    запись оттуда приходит самими данными, а не именем файла на чужой
    машине, и заводить ради неё временный файл значило бы писать на диск
    то, что не хранится (см. `answers.VoiceSpec`).
    """
    source = path if hasattr(path, "read") else str(path)
    with wave.open(source, "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())

    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"Неподдерживаемая разрядность WAV: {width * 8} бит")
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if width == 1:                       # 8-битный PCM беззнаковый
        data = (data - 128.0) / 128.0
    else:
        data /= float(np.iinfo(dtype).max)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def resample(signal: np.ndarray, source_rate: int,
             target_rate: int = TARGET_RATE) -> np.ndarray:
    """Линейная передискретизация. Для признаков речи её достаточно."""
    if source_rate == target_rate or signal.size == 0:
        return signal
    count = int(round(signal.size * target_rate / source_rate))
    if count <= 1:
        return signal
    source_points = np.linspace(0.0, 1.0, signal.size)
    target_points = np.linspace(0.0, 1.0, count)
    return np.interp(target_points, source_points, signal).astype(np.float32)


#: Ниже какой амплитуды запись считается пустой.
#:
#: Нужен ИМЕННО абсолютный порог, хотя весь модуль построен на отказе от
#: абсолютных порогов. Противоречия нет: там порог решал бы, ВЕРНО ли
#: произнесено слово, — это и требует калибровки под голос; здесь он
#: решает, есть ли в файле вообще звук, а это свойство самого файла.
SILENCE_PEAK = 0.01


def is_silent(signal: np.ndarray) -> bool:
    """
    Есть ли в записи хоть что-нибудь.

    Замер, из-за которого проверка появилась: запись тишины получала
    вердикт «больше похоже на Terabyte». Правило ближайшего работает и на
    тишине — расстояния конечны, и какое-то из них наименьшее, — но
    смысла у такого вердикта нет: сравнивать не с чем со стороны СТУДЕНТА.
    Тишина обязана давать отказ, а не название случайного слова.

    `trim_silence` эту роль исполнять не может: его порог ОТНОСИТЕЛЬНЫЙ,
    доля от максимума, и у сплошной тишины он вырождается.
    """
    return signal.size == 0 or float(np.max(np.abs(signal))) < SILENCE_PEAK


def trim_silence(signal: np.ndarray, threshold: float = 0.02) -> np.ndarray:
    """
    Обрезать тишину по краям.

    Без обрезки запись студента, нажавшего «стоп» с задержкой, отличается
    от эталона в основном длиной паузы — и выравнивание по времени будет
    подгонять тишину вместо звука.
    """
    if signal.size == 0:
        return signal
    loud = np.abs(signal) > (threshold * np.max(np.abs(signal)) + 1e-9)
    if not loud.any():
        return signal
    first, last = np.argmax(loud), signal.size - np.argmax(loud[::-1])
    return signal[first:last]


# ------------------------------------------------------------ признаки

def _mel(frequency: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + frequency / 700.0)


def _mel_inverse(mel: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _filterbank(size: int, rate: int, count: int = MEL_FILTERS) -> np.ndarray:
    """Треугольные фильтры, равномерные по мел-шкале."""
    low, high = _mel(np.array(0.0)), _mel(np.array(rate / 2.0))
    points = _mel_inverse(np.linspace(low, high, count + 2))
    bins = np.floor((size + 1) * points / rate).astype(int)
    bank = np.zeros((count, size // 2 + 1), dtype=np.float32)
    for i in range(count):
        left, centre, right = bins[i], bins[i + 1], bins[i + 2]
        if centre == left:
            centre = left + 1
        if right == centre:
            right = centre + 1
        right = min(right, bank.shape[1] - 1)
        centre = min(centre, right - 1) if right > 0 else centre
        for k in range(left, centre):
            if 0 <= k < bank.shape[1]:
                bank[i, k] = (k - left) / max(1, centre - left)
        for k in range(centre, right):
            if 0 <= k < bank.shape[1]:
                bank[i, k] = (right - k) / max(1, right - centre)
    return bank


def mfcc(signal: np.ndarray, rate: int = TARGET_RATE) -> np.ndarray:
    """
    Мел-кепстральные коэффициенты: матрица «кадры × коэффициенты».

    Классическая цепочка: предыскажение → окно Хэмминга → спектр
    мощности → мел-фильтры → логарифм → дискретное косинусное
    преобразование. Нулевой коэффициент отбрасывается: он несёт
    громкость, а громкость записи к произношению отношения не имеет.

    Признаки нормируются по каждому коэффициенту (среднее вычитается).
    Это снимает постоянную составляющую канала — разницу микрофонов,
    которая иначе доминировала бы над разницей слов.
    """
    signal = trim_silence(np.asarray(signal, dtype=np.float32))
    if signal.size < 2:
        return np.zeros((0, CEPSTRA - 1), dtype=np.float32)

    emphasized = np.append(signal[0], signal[1:] - 0.97 * signal[:-1])
    frame_len = max(8, int(round(FRAME_SEC * rate)))
    step = max(1, int(round(STEP_SEC * rate)))
    if emphasized.size < frame_len:
        emphasized = np.pad(emphasized, (0, frame_len - emphasized.size))

    count = 1 + (emphasized.size - frame_len) // step
    indices = (np.arange(frame_len)[None, :]
               + step * np.arange(count)[:, None])
    frames = emphasized[indices] * np.hamming(frame_len)

    size = 1
    while size < frame_len:
        size *= 2
    spectrum = np.abs(np.fft.rfft(frames, n=size)) ** 2 / size
    bank = _filterbank(size, rate)
    energies = np.maximum(spectrum @ bank.T, 1e-10)
    log_energies = np.log(energies)

    n = log_energies.shape[1]
    basis = np.cos(np.pi / n * (np.arange(n)[None, :] + 0.5)
                   * np.arange(CEPSTRA)[:, None])
    cepstra = log_energies @ basis.T
    features = cepstra[:, 1:]                      # без нулевого — громкость
    if features.shape[0] == 0:
        return features.astype(np.float32)
    features = features - features.mean(axis=0, keepdims=True)
    return features.astype(np.float32)


def features_of(path) -> np.ndarray:
    """Признаки звукового файла: чтение, приведение частоты, MFCC."""
    signal, rate = read_wav(path)
    return mfcc(resample(signal, rate), TARGET_RATE)


# --------------------------------------------------------- сопоставление

def dtw_distance(a: np.ndarray, b: np.ndarray) -> float:
    """
    Расстояние динамического выравнивания между двумя наборами признаков.

    Выравнивание по времени нужно потому, что одно и то же слово
    произносят с разной скоростью и с разной длиной гласных. Обычное
    покадровое сравнение считало бы это разными словами.

    Результат нормирован длиной пути: иначе длинные слова оказывались бы
    «дальше» просто за счёт числа кадров.

    Считается ПО АНТИДИАГОНАЛЯМ, а не построчно. Значение то же самое —
    рекуррента не тронута, — но зависимости у ячеек одной антидиагонали
    нет, и вся она считается одним действием numpy. Замер, из-за которого
    это понадобилось: посимвольный обход стоил 3.65 с на один ответ в
    задании на произношение (окрестность из 12 эталонов, самый длинный —
    510 кадров), потому что интерпретатор проходил четверть миллиона
    ячеек по одной. Ждать столько после каждой записи нельзя.
    """
    if a.shape[0] == 0 or b.shape[0] == 0:
        return float("inf")
    # Матрица попарных евклидовых расстояний.
    cost = np.sqrt(np.maximum(
        ((a ** 2).sum(axis=1)[:, None] + (b ** 2).sum(axis=1)[None, :]
         - 2.0 * a @ b.T), 0.0))
    rows, cols = cost.shape

    # Диагональ номер d — это ячейки, у которых i + j = d. Каждая зависит
    # от двух ячеек диагонали d-1 (слева и сверху) и одной диагонали d-2
    # (наискось), поэтому в памяти держатся ровно две последние.
    # Индексом внутри диагонали служит i: так соседи находятся сдвигом,
    # а не пересчётом координат.
    previous = np.full(rows + 1, np.inf, dtype=np.float64)   # d - 2
    current = np.full(rows + 1, np.inf, dtype=np.float64)    # d - 1
    previous[0] = 0.0                                        # acc[0, 0]

    for d in range(2, rows + cols + 1):
        low, high = max(1, d - cols), min(rows, d - 1)
        following = np.full(rows + 1, np.inf, dtype=np.float64)
        if low <= high:
            i = np.arange(low, high + 1)
            best = np.minimum(np.minimum(current[i],        # acc[i, j-1]
                                         current[i - 1]),   # acc[i-1, j]
                              previous[i - 1])              # acc[i-1, j-1]
            following[i] = cost[i - 1, d - i - 1] + best
        previous, current = current, following

    return float(current[rows] / (rows + cols))


def separation_of(term: str, references: Mapping[str, np.ndarray],
                  cache: Optional[dict] = None) -> float:
    """
    Расстояние от эталона `term` до БЛИЖАЙШЕГО ЧУЖОГО эталона словаря.

    Это окрестность в чистом виде: величина считается по одним эталонам и
    о записи студента ничего не знает. Прямой аналог `word_tolerance`:
    там допуск ограничен расстоянием до ближайшего другого термина, здесь
    тем же расстоянием задан масштаб уверенности.

    Стоит n−1 выравниваний — и только для ОДНОГО слова. Считать сразу для
    всех (n²/2 выравниваний) незачем: за попытку нужен масштаб одного
    победителя. Замер: полная таблица добавляла к первой проверке 0.47 с,
    ленивая — 0.1 с, и в обоих случаях повторные попытки бесплатны.

    `cache` — словарь, который заполняется по мере надобности. Он же
    делает вторую попытку с тем же победителем бесплатной.
    """
    if cache is not None and term in cache:
        return cache[term]
    own = references.get(term)
    value = float("inf")
    if own is not None:
        for other, features in references.items():
            if other == term:
                continue
            distance = dtw_distance(own, features)
            if distance < value:
                value = distance
    if cache is not None:
        cache[term] = value
    return value


def separations(references: Mapping[str, np.ndarray]) -> dict[str, float]:
    """
    То же для ВСЕХ слов сразу: `слово → расстояние до ближайшего чужого`.

    Нужна замерам, которые всё равно обходят словарь целиком. В проверке
    ответа пользуются `separation_of`: там за попытку требуется масштаб
    одного слова, а не всей таблицы.
    """
    terms = list(references)
    out = {term: float("inf") for term in terms}
    for i, first in enumerate(terms):
        for second in terms[i + 1:]:
            distance = dtw_distance(references[first], references[second])
            if distance < out[first]:
                out[first] = distance
            if distance < out[second]:
                out[second] = distance
    return out


def match(recording: np.ndarray,
          references: Mapping[str, np.ndarray],
          *, gaps: Optional[Mapping[str, float]] = None) -> Optional[Match]:
    """
    Найти слово словаря, чей эталон ближе всего к записи.

    `references` — уже посчитанные признаки эталонов. Считать их на
    каждую попытку нельзя: словарь из двадцати слов пересчитывался бы
    целиком на каждый ответ.

    `gaps` — известные межэталонные расстояния. Словарь может быть
    НЕПОЛНЫМ и даже пустым: чего в нём нет, досчитывается здесь, и если
    он изменяемый — запоминается в нём же. Так вызывающему не нужно
    решать заранее, какие слова понадобятся; достаточно один раз завести
    словарь и передавать его дальше.
    """
    if recording.shape[0] == 0 or not references:
        return None
    ranked = sorted(((dtw_distance(recording, reference), term)
                     for term, reference in references.items()),
                    key=lambda pair: pair[0])
    best_distance, best_term = ranked[0]
    if len(ranked) > 1:
        second_distance, second_term = ranked[1]
    else:
        second_distance, second_term = float("inf"), None
    gap = gaps.get(best_term) if gaps is not None else None
    if gap is None:
        gap = separation_of(best_term, references,
                            gaps if isinstance(gaps, dict) else None)
    return Match(term=best_term, distance=best_distance,
                 runner_up=second_term, runner_up_distance=second_distance,
                 separation=gap)


def accepts(expected: str, recording: np.ndarray,
            references: Mapping[str, np.ndarray], *,
            require_confident: bool = False,
            gaps: Optional[Mapping[str, float]] = None) -> bool:
    """
    Принять ли запись как произнесённое `expected`.

    `require_confident` — требовать не только первого места, но и отрыва
    от следующего. Для зачёта это разумно: вердикт «наугад» там дороже
    отказа проверить.
    """
    found = match(recording, references, gaps=gaps)
    if found is None or found.term != expected:
        return False
    return found.confident if require_confident else True


def reference_features(terms: Iterable[str],
                       resolve) -> dict[str, np.ndarray]:
    """
    Посчитать признаки эталонов для набора слов.

    `resolve(term)` возвращает путь к WAV (или открытый поток) либо None.
    Слова без эталона молча пропускаются: словарь без звука — норма, а не
    поломка.
    """
    out: dict[str, np.ndarray] = {}
    for term in terms:
        path = resolve(term)
        if path is None:
            continue
        try:
            features = features_of(path)
        except (OSError, ValueError, EOFError, wave.Error):
            continue
        if features.shape[0]:
            out[term] = features
    return out


def vocabulary_confusions(references: Mapping[str, np.ndarray],
                          ) -> list[tuple[str, str, float]]:
    """
    Пары слов, чьи эталоны неразличимы правилом.

    Прямой аналог `word_tolerance.vocabulary_collisions`: главное
    свойство проверяется прогоном по настоящему словарю, а не
    рассуждением о порогах. Пустой список — каждое слово опознаётся
    своим эталоном.
    """
    found: list[tuple[str, str, float]] = []
    for term, features in references.items():
        result = match(features, references)
        if result is not None and result.term != term:
            found.append((term, result.term, result.distance))
    return found


def perturb(signal: np.ndarray, *, speed: float = 1.0,
            noise: float = 0.0, gain: float = 1.0,
            seed: int = 0) -> np.ndarray:
    """
    Исказить запись, изображая другого говорящего и другой микрофон.

    Нужна для ПРОВЕРКИ правила там, где живых записей нет: темп, шум и
    громкость — три различия, которые заведомо есть между дикторами.
    Это не замена записям людей, а нижняя граница: правило, не пережившее
    искусственного искажения, не переживёт и настоящего.
    """
    out = np.asarray(signal, dtype=np.float32)
    if speed != 1.0 and out.size > 1:
        count = max(2, int(round(out.size / speed)))
        out = np.interp(np.linspace(0.0, 1.0, count),
                        np.linspace(0.0, 1.0, out.size), out).astype(np.float32)
    if gain != 1.0:
        out = out * gain
    if noise > 0.0:
        rng = np.random.default_rng(seed)
        amplitude = noise * (np.max(np.abs(out)) if out.size else 1.0)
        out = out + rng.normal(0.0, amplitude, out.size).astype(np.float32)
    return out
