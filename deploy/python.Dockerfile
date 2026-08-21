# Образ обеих Python-служб: generator_service и contour_service.
#
# Почему ОДИН образ на две службы, а не два
# -----------------------------------------
# Службы живут в одном монорепо, тянут один `requirements.txt` и импортируют
# одно ядро. Два образа отличались бы только строкой запуска — то есть не
# отличались бы ничем, кроме шанса разъехаться по версиям зависимостей.
# Разная у них команда, а не сборка: см. `docker-compose.yml`.
#
# Собирается из КОРНЯ монорепо:
#     docker build -f deploy/python.Dockerfile -t generation/python .

FROM python:3.11-slim

# Qt приезжает не по недосмотру: `core/rendering.py` — общий код с
# десктопом, и на сервере он тоже рисует (формулы, графики, картинки в
# заданиях). Библиотеки ниже — то, без чего PyQt6 не импортируется даже
# в offscreen: проверено тем, что без них падает `import core`.
RUN apt-get update && apt-get install --yes --no-install-recommends \
        libgl1 \
        libegl1 \
        libglib2.0-0 \
        libdbus-1-3 \
        libxkbcommon0 \
        libfontconfig1 \
        libfreetype6 \
    && rm --recursive --force /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Без дисплея Qt не поднимется, а он тут есть всегда (см. выше).
    QT_QPA_PLATFORM=offscreen \
    # Данные — на томе, а не в образе. Это и есть причина, по которой
    # рабочая база отделена от поставки: слой образа доступен только на
    # чтение, и пока база лежала в `resources/`, служба не запускалась бы.
    GEN_DATA_DIR=/data

WORKDIR /app

# Зависимости отдельным слоем: правка кода не пересобирает pip.
COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

# Дальше — только то, что службам нужно в работе. Фронтенд, web_layer,
# тесты десктопа и `tools/` в образ не едут.
COPY const.py bootstrap.py ./
COPY core ./core
COPY exercises ./exercises
COPY generator_service ./generator_service
COPY contour_service ./contour_service
COPY scripts ./scripts
# Поставка: словари, звук, транскрипции и ШАБЛОН базы.
COPY resources ./resources
# База знаний читается из исходных файлов (`core/guide.py`), а не из
# сборки фронтенда: правки из редактора ложатся ПОВЕРХ вот этих страниц.
COPY docs/guide ./docs/guide

# Не от root: службе нужно писать только в /data, всё остальное — чтение.
RUN useradd --system --create-home --uid 10001 generation \
    && mkdir --parents /data \
    && chown generation:generation /data
USER generation

EXPOSE 8000
CMD ["uvicorn", "generator_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
