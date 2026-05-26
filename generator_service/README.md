# core — ядро генератора заданий (веб-готовая версия)

Это та же кодовая база, что и в десктопном репозитории, но с минимальными
правками для встраивания в FastAPI-микросервис. Десктопное приложение
с этим ядром продолжает работать **без каких-либо изменений** в `ui/`,
`exercises/`, `resources/` или `bootstrap.py`.

## Что изменилось относительно десктоп-версии

Ровно четыре вещи. Все они проверены тестом `tests/test_serialization.py`.

**1. PyQt6 импортируется лениво.** В десктопной версии `core/blocks.py`,
`core/dynamic_blocks.py` и `core/rendering.py` подтягивали PyQt6 на
уровне модуля. Это означало, что `from core import TextBlock` в любом
процессе тащил за собой ~50 МБ Qt-библиотек и падал на серверах без
дисплея. Теперь Qt-импорты переехали внутрь методов `render_qt()`
и других Qt-функций. На десктопе ничего не меняется — первое же
обращение к `render_qt` импортирует PyQt6. На сервере метод никогда
не зовётся и PyQt6 не нужен вообще; в `requirements.txt` его больше нет.

**2. Добавлен абстрактный метод `Block.to_dict()`.** Это четвёртый метод
полиморфного рендеринга, рядом с `render_qt` / `render_plain` / `render_docx`.
Реализован для всех семи существующих блоков. Каждый блок сам знает,
как сериализоваться в JSON для веб-API:

| Блок | Поле `type` | Что в словаре |
|---|---|---|
| `TextBlock` | `"text"` | `content` |
| `FormulaBlock` | `"formula"` | `latex`, `image_b64` (PNG в base64) |
| `ImageBlock` | `"image"` | `image_b64`, `caption` |
| `CodeBlock` | `"code"` | `code`, `language` |
| `TableBlock` | `"table"` | `rows`, `header` |
| `FillInTheBlankBlock` | `"fill_in_blank"` | `template`, `answers`, `placeholder`, `case_sensitive` |
| `WordCorrectionBlock` | `"word_correction"` | `translation`, `user_answer`, `expected`, `correct`, `tolerant_accept`, `diff` |

Соответственно `StaticTask.to_dict()`, `TurnResult.to_dict()`, `Subject.to_dict()`,
`Partition.to_dict()` сериализуют составные сущности через `to_dict()` своих
полей. Это сохраняет принцип стандарта: ядро не знает о типах блоков,
сериализация полиморфна — добавление нового блока не требует правки
FastAPI-сервиса.

Важная деталь сериализации `WordCorrectionBlock`: в десктопе он рендерит
diff в HTML-строку, но в `to_dict()` diff отдаётся **структурированно** —
списком операций `{"op": "equal|replace|delete|insert", "user": "...", "expected": "..."}`.
Это безопаснее (фронт не обязан использовать `dangerouslySetInnerHTML`)
и позволяет React-компонентам стилизовать ошибки нативно.

**3. Добавлена функция `latex_to_png_bytes()` в `core/rendering.py`.**
Она стала базовой — `latex_to_pixmap` (Qt) и `latex_to_docx_image` (docx)
теперь оба вызывают её. И `FormulaBlock.to_dict()` тоже использует её.
Одна точка истины для рендера формул вместо трёх параллельных пайплайнов.

Заодно добавлена `image_to_png_bytes()` для `ImageBlock.to_dict()` —
универсальная конвертация PIL/bytes/путь → PNG-байты.

**4. `_safe_meta()` в `core/task.py`.** `StaticTask.meta` — это словарь,
в который генераторы кладут что попало (числовые значения, иногда списки,
изредка PIL-картинки). При сериализации в JSON это может уронить запрос.
`_safe_meta` рекурсивно фильтрует словарь: примитивы пропускаются,
сложные объекты приводятся к `str()`. Защитный механизм, на десктопе
никак не проявляется.

## Что НЕ менялось

Сравните с десктоп-версией — изменения только в:

- `core/content.py` — добавлен абстрактный `to_dict()`
- `core/blocks.py` — lazy Qt + `to_dict()` для 5 блоков
- `core/dynamic_blocks.py` — lazy Qt + `to_dict()` для 2 блоков
- `core/rendering.py` — lazy Qt + новые `latex_to_png_bytes` и `image_to_png_bytes`
- `core/task.py` — `to_dict()` для `StaticTask`, `TurnResult`, плюс `_safe_meta`
- `core/repository.py` — `to_dict()` для `Subject`, `Partition` (одна строка кода логики не тронута)
- `requirements.txt` — удалён PyQt6

Остальные файлы скопированы **байт-в-байт** из десктоп-репозитория:
- `core/latex.py`
- `core/generator.py`
- `core/registry.py`
- `core/composites.py`
- `core/word_stats.py`
- `core/__init__.py`

## Структура папки

```
core/
├── core/                        # Сам Python-пакет
│   ├── __init__.py             # публичный API (без изменений)
│   ├── content.py              # ИЗМЕНЕНО: +to_dict abstract
│   ├── blocks.py               # ИЗМЕНЕНО: lazy Qt + to_dict
│   ├── dynamic_blocks.py       # ИЗМЕНЕНО: lazy Qt + to_dict
│   ├── rendering.py            # ИЗМЕНЕНО: lazy Qt + latex_to_png_bytes
│   ├── task.py                 # ИЗМЕНЕНО: to_dict + _safe_meta
│   ├── repository.py           # ИЗМЕНЕНО: to_dict у Subject/Partition
│   ├── latex.py                # без изменений
│   ├── generator.py            # без изменений
│   ├── registry.py             # без изменений
│   ├── composites.py           # без изменений
│   └── word_stats.py           # без изменений
│
├── tests/
│   └── test_serialization.py   # smoke-тест: headless + to_dict
│
├── requirements.txt            # без PyQt6
└── README.md                   # этот файл
```

## Файлы, которые нужно скопировать из десктоп-репо

Эти папки не лежат в текущем репозитории (для веб-сервиса они идут
без изменений и потяжелее), но обязательны для запуска:

```
exercises/                      # все доменные модули (linal/, matan/, fisic/, opvs/, english/)
resources/                      # users_database.db + words/*.json
bootstrap.py                    # сборка реестра (без изменений)
const.py                        # пути проекта (без изменений)
```

Скопируйте их корневую папку рядом с `core/` и `tests/`. После этого
структура будет полная — десктоп-`ui/` тоже подключится без правок.

## Установка и проверка

```bash
# Headless-режим (для FastAPI)
pip install -r requirements.txt
python tests/test_serialization.py
```

Ожидаемый вывод теста — 12 пройденных проверок, в том числе:

```
✓ headless-импорт работает: PyQt6 не подтягивается
✓ FormulaBlock.to_dict (PNG: есть)
✓ StaticTask.to_dict (полный JSON: ~7-8 КБ)
```

Если запустить тест в окружении с установленным PyQt6, он всё равно
пройдёт — но первая проверка не докажет headless-готовность. Для
надёжной проверки используйте чистый venv:

```bash
python -m venv .venv-headless
source .venv-headless/bin/activate   # или .venv-headless\Scripts\activate на Windows
pip install -r requirements.txt
python tests/test_serialization.py
```

## Контракт JSON для следующих шагов

`StaticTask.to_dict()` уже выдаёт ровно тот формат, что описан в
архитектурном плане, секция 1.2:

```json
{
  "type": "static",
  "statement": [
    { "type": "text", "content": "Найдите производную:" },
    { "type": "formula", "latex": "f(x) = x^2", "image_b64": "iVBOR..." }
  ],
  "answer": [
    { "type": "formula", "latex": "f'(x) = 2x", "image_b64": "iVBOR..." }
  ],
  "meta": { "partition_id": 40 }
}
```

Это означает, что FastAPI-обёртка на втором шаге станет тривиальной:
эндпоинт `/generate` буквально вызовет `task.to_dict()` и вернёт
результат. Никакого «огромного `isinstance`-каскада в `serializers.py`»,
как было в исходном плане — каждый блок сам знает, как себя сериализовать,
и это полностью соответствует архитектурному стандарту проекта.
