"""
Smoke-тест правок ядра под веб-сервис.

Проверяет три вещи:
  1. Все блоки и задачи импортируются БЕЗ установленного PyQt6
     (lazy-импорт перенесён в render_qt и работает).
  2. У каждого блока есть to_dict(), возвращающий валидный JSON.
  3. StaticTask.to_dict() корректно сериализует вложенные блоки.

Запуск:
    cd core
    python -m tests.test_serialization

или
    cd core
    python tests/test_serialization.py

Если установлен PyQt6 — тест всё равно пройдёт, но пункт 1 не докажет
headless-готовность. Чтобы убедиться окончательно, удалите PyQt6 из
окружения (например, в свежем venv) и запустите снова.
"""

from __future__ import annotations
import json
import os
import sys
import traceback

# Делаем пакет `core/` доступным независимо от того, откуда запущен скрипт.
# Корень репозитория — папка-родитель папки tests/.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ────────────────────────────────────────────────────────────────────────────
# 1. Проверка headless-импорта
# ────────────────────────────────────────────────────────────────────────────

def test_headless_imports():
    """
    Импорт ядра не должен подымать PyQt6 раньше времени.

    Если PyQt6 был импортирован, значит, какой-то модуль ядра тянет
    его на уровне `import` — нужно перевести этот импорт в lazy.
    """
    # Стираем все PyQt6.* модули, если они были загружены (например,
    # десктопом во время разработки). Тест корректен только на «чистом»
    # старте, потому что мы хотим проверить: тащит ли ядро PyQt сам.
    for name in list(sys.modules):
        if name.startswith("PyQt6"):
            del sys.modules[name]

    # Импортируем ядро
    from core import (
        Block, TextBlock, FormulaBlock, ImageBlock, CodeBlock, TableBlock,
        FillInTheBlankBlock, WordCorrectionBlock,
        StaticTask, TurnResult,
        Subject, Partition,
    )

    pyqt_modules = [m for m in sys.modules if m.startswith("PyQt6")]
    if pyqt_modules:
        raise AssertionError(
            f"После импорта core/ загружены PyQt6-модули: {pyqt_modules}. "
            "Какой-то модуль тянет PyQt на уровне `import`. "
            "Lazy-импорт сломан."
        )
    print("✓ headless-импорт работает: PyQt6 не подтягивается")


# ────────────────────────────────────────────────────────────────────────────
# 2. Проверка to_dict() у всех блоков
# ────────────────────────────────────────────────────────────────────────────

def _assert_json_serializable(d, label: str):
    """Убеждаемся, что dict проходит через json.dumps без потерь."""
    try:
        json.dumps(d, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise AssertionError(
            f"{label}: to_dict() вернул не JSON-сериализуемый объект — {e}"
        )


def test_text_block():
    from core import TextBlock
    b = TextBlock("Найдите производную функции")
    d = b.to_dict()
    assert d["type"] == "text"
    assert d["content"] == "Найдите производную функции"
    _assert_json_serializable(d, "TextBlock")
    print("✓ TextBlock.to_dict")


def test_formula_block():
    from core import FormulaBlock
    b = FormulaBlock(r"x^2 + 2x + 1")
    d = b.to_dict()
    assert d["type"] == "formula"
    assert d["latex"] == r"x^2 + 2x + 1"
    # image_b64 может быть None, если matplotlib не справился, но поле должно быть
    assert "image_b64" in d
    if d["image_b64"] is not None:
        # Простая проверка: это похоже на base64-строку
        assert isinstance(d["image_b64"], str)
        assert len(d["image_b64"]) > 100, "base64 PNG неподозрительно короткий"
    _assert_json_serializable(d, "FormulaBlock")
    print(f"✓ FormulaBlock.to_dict (PNG: {'есть' if d['image_b64'] else 'нет, fallback'})")


def test_image_block():
    from core import ImageBlock
    from PIL import Image as PILImage
    # Мини-картинка 4×4
    img = PILImage.new("RGB", (4, 4), color=(255, 0, 0))
    b = ImageBlock(img, caption="Тестовое изображение")
    d = b.to_dict()
    assert d["type"] == "image"
    assert d["caption"] == "Тестовое изображение"
    assert d["image_b64"] is not None
    assert isinstance(d["image_b64"], str)
    _assert_json_serializable(d, "ImageBlock")
    print("✓ ImageBlock.to_dict")


def test_code_block():
    from core import CodeBlock
    b = CodeBlock("int main() { return 0; }", language="c")
    d = b.to_dict()
    assert d["type"] == "code"
    assert d["code"] == "int main() { return 0; }"
    assert d["language"] == "c"
    _assert_json_serializable(d, "CodeBlock")
    print("✓ CodeBlock.to_dict")


def test_table_block():
    from core import TableBlock
    b = TableBlock([["1", "2"], ["3", "4"]], header=["A", "B"])
    d = b.to_dict()
    assert d["type"] == "table"
    assert d["rows"] == [["1", "2"], ["3", "4"]]
    assert d["header"] == ["A", "B"]
    _assert_json_serializable(d, "TableBlock")
    print("✓ TableBlock.to_dict")


def test_fill_in_blank():
    from core import FillInTheBlankBlock
    b = FillInTheBlankBlock("I ___ a student.", answers=["am"])
    d = b.to_dict()
    assert d["type"] == "fill_in_blank"
    assert d["template"] == "I ___ a student."
    assert d["answers"] == ["am"]
    assert d["placeholder"] == "___"
    _assert_json_serializable(d, "FillInTheBlankBlock")
    print("✓ FillInTheBlankBlock.to_dict")


def test_word_correction():
    from core import WordCorrectionBlock
    b = WordCorrectionBlock(
        translation="яблоко",
        user_answer="appel",
        expected="apple",
        correct=False,
    )
    d = b.to_dict()
    assert d["type"] == "word_correction"
    assert d["translation"] == "яблоко"
    assert d["user_answer"] == "appel"
    assert d["expected"] == "apple"
    assert d["correct"] is False
    assert isinstance(d["diff"], list)
    assert all("op" in op for op in d["diff"])
    _assert_json_serializable(d, "WordCorrectionBlock")
    print(f"✓ WordCorrectionBlock.to_dict (diff: {len(d['diff'])} ops)")


# ────────────────────────────────────────────────────────────────────────────
# 3. Проверка StaticTask.to_dict() — composite сериализация
# ────────────────────────────────────────────────────────────────────────────

def test_static_task():
    from core import StaticTask, TextBlock, FormulaBlock
    t = StaticTask(
        statement=[
            TextBlock("Найдите производную:"),
            FormulaBlock(r"f(x) = x^2"),
        ],
        answer=[FormulaBlock(r"f'(x) = 2x")],
        meta={"partition_id": 40},
    )
    d = t.to_dict()
    assert d["type"] == "static"
    assert len(d["statement"]) == 2
    assert d["statement"][0]["type"] == "text"
    assert d["statement"][1]["type"] == "formula"
    assert len(d["answer"]) == 1
    assert d["meta"]["partition_id"] == 40
    _assert_json_serializable(d, "StaticTask")
    print(f"✓ StaticTask.to_dict (полный JSON: {len(json.dumps(d))} байт)")


def test_turn_result_finished():
    from core import TurnResult, TextBlock, WordCorrectionBlock
    r = TurnResult(
        correct=True,
        feedback=[WordCorrectionBlock("яблоко", "apple", "apple", True)],
        next_prompt=None,  # сессия завершена
    )
    d = r.to_dict()
    assert d["correct"] is True
    assert d["next_prompt"] is None
    assert d["is_finished"] is True
    _assert_json_serializable(d, "TurnResult (finished)")
    print("✓ TurnResult.to_dict (завершённая сессия)")


def test_turn_result_continuing():
    from core import TurnResult, TextBlock
    r = TurnResult(
        correct=False,
        feedback=[TextBlock("Неверно, попробуйте ещё")],
        next_prompt=[TextBlock("Переведите: дом")],
    )
    d = r.to_dict()
    assert d["is_finished"] is False
    assert d["next_prompt"][0]["content"] == "Переведите: дом"
    _assert_json_serializable(d, "TurnResult (continuing)")
    print("✓ TurnResult.to_dict (продолжающаяся сессия)")


def test_subject_partition():
    from core import Subject, Partition
    s = Subject(id=1, name="Линейная алгебра", parent_name="Линейная алгебра")
    p = Partition(
        id=40, subject_id=10, name="Обычные производные",
        constracted=0, generation_params={},
    )
    sd = s.to_dict()
    pd = p.to_dict()
    assert sd["id"] == 1
    assert pd["constracted"] == 0
    assert "generation_params" not in pd, (
        "Partition.to_dict() не должен раскрывать generation_params в публичном API"
    )
    _assert_json_serializable(sd, "Subject")
    _assert_json_serializable(pd, "Partition")
    print("✓ Subject.to_dict, Partition.to_dict")


# ────────────────────────────────────────────────────────────────────────────
# Runner
# ────────────────────────────────────────────────────────────────────────────

TESTS = [
    test_headless_imports,
    test_text_block,
    test_formula_block,
    test_image_block,
    test_code_block,
    test_table_block,
    test_fill_in_blank,
    test_word_correction,
    test_static_task,
    test_turn_result_finished,
    test_turn_result_continuing,
    test_subject_partition,
]


def main():
    print("─" * 60)
    print(" Smoke-тест ядра под веб-сервис")
    print("─" * 60)
    passed = 0
    failed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
        except Exception:
            print(f"✗ {test.__name__} провалился:")
            traceback.print_exc()
            failed += 1
    print("─" * 60)
    print(f" Итог: {passed} пройдено, {failed} провалено")
    print("─" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
