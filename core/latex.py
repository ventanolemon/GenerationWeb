"""
core/latex.py — единая обработка LaTeX перед рендерингом.

В проекте в разные точки времени LaTeX может приходить в нескольких разных
формах. Это исторически сложилось из-за модулей матана: каждый из них
по-своему "украшает" вывод sympy для отображения в русской математической
нотации (tg вместо \\tan, ln вместо \\log и т.п.).

Этот модуль приводит ЛЮБОЙ входящий LaTeX к ОДНОМУ каноническому виду:

  canonical_latex(s)         — стандартный LaTeX, понятный matplotlib mathtext.
                              Используется и для Qt-предпросмотра,
                              и для конвертации формул в картинки в docx.

  for_word_omath(s)          — отдельный вариант для нативной вставки в Word
                              через win32com.OMaths.BuildUp(): убирает
                              \\left/\\right, исправляет ^ { → ^{, и т.п.
                              Заходит в эту функцию канонический LaTeX,
                              выходит — то, что Word OMath съест без ошибок.

Дальше в коде НИГДЕ больше нет правил .replace('\\tan', 'tg') и подобного.
Все правила сосредоточены здесь.

Источник правил:
  * fh.py / teylor.py / parametric_task.py — clean_latex_for_word
    (полный набор правил для Word).
  * just_diff.py / ln_diff.py / equals.py / ... — clear_latex
    (упрощённый набор — sympy → русифицированный).
"""

from __future__ import annotations
import re


# ============================================================
# 1. Канонизация LaTeX → стандартный (для matplotlib mathtext)
# ============================================================
#
# Что может прийти на вход (всё реально встречается в матан-модулях):
#
#   а) Чистый sympy:        \tan{(x)}, \log{(x)}, \operatorname{atan}{(x)}
#   б) "Русифицированный":  tg{(x)},   ln{(x)},   arctg{(x)}, arcsin{(x)}
#   в) Смешанный:           \sin{...} рядом с tg{...}
#   г) Сборка вручную:      "y=" + sp.latex(...) — sympy с префиксом
#   д) Особые конструкции:  \matrix{a\\b}, \cases, \text{в точке}
#
# canonical_latex берёт любой из этих форматов и возвращает стандартный
# LaTeX, который matplotlib mathtext умеет рендерить.

# Соответствие "русское имя функции" → стандартный LaTeX.
# Порядок важен: длинные имена первыми, иначе arctg попадёт под tg.
_BARE_TO_STANDARD = [
    ("arcctg",  r"\operatorname{arcctg}"),
    ("arcsin",  r"\arcsin"),
    ("arccos",  r"\arccos"),
    ("arctg",   r"\arctan"),
    ("ctg",     r"\cot"),
    ("tg",      r"\tan"),
    ("sh",      r"\sinh"),
    ("ch",      r"\cosh"),
    ("th",      r"\tanh"),
]


def canonical_latex(latex: str) -> str:
    """
    Нормализовать LaTeX до стандартного формата, понятного matplotlib mathtext.

    Что происходит:
      * tg/ctg/arctg/arcsin/arccos/sh/ch — обратная замена в \\tan/\\cot/...
      * \\operatorname{atan/asin/acos} — заменяются на стандартные \\arctan/\\arcsin
      * \\matrix{a\\\\b\\\\c} — преобразуется в "a,\\ b,\\ c"
      * \\cases{a & b} — аналогично, через запятую
      * \\text{...} — превращается в обычный текст (mathtext не любит)
      * ^ { и _ { (пробелы) — выправляются
      * \\, \\; \\quad — превращаются в обычные пробелы
      * \\mathrm{e}, \\mathit{e} → e
    """
    s = latex

    # 1. Исправить ^ { и _ {  (типичная проблема sp.latex с pretty=True)
    s = s.replace("^ {", "^{").replace("^  {", "^{")
    s = s.replace("_ {", "_{").replace("_  {", "_{")

    # 2. Убрать тонкие пробелы и quad — mathtext рендерит, но часто рушится
    s = s.replace(r"\,", " ").replace(r"\;", " ").replace(r"\quad", " ")

    # 3. \mathrm{e}, \mathit{e} → e (часто sympy выдаёт так)
    s = re.sub(r"\\mathrm\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\mathit\{([^}]*)\}", r"\1", s)

    # 4. \text{...} → просто содержимое (без mathmode-стилизации)
    #    mathtext не умеет \text внутри $$, но текст может пригодиться рядом.
    s = re.sub(r"\\text\{([^}]*)\}", r"\\mathrm{\1}", s)

    # 5. \operatorname{name} → стандартная функция, если знаем такую
    #    Например, \operatorname{atan} → \arctan
    s = s.replace(r"\operatorname{atan}", r"\arctan")
    s = s.replace(r"\operatorname{asin}", r"\arcsin")
    s = s.replace(r"\operatorname{acos}", r"\arccos")
    s = s.replace(r"\operatorname{actg}", r"\operatorname{arccot}")
    # Остальное \operatorname{X} оставляем — mathtext его поддерживает

    # 6. \matrix{a\\b\\c} → "a,\\ b,\\ c"   (с подсчётом скобок для вложенностей)
    s = _expand_braced_macro(s, "\\matrix{")

    # 7. \cases{a & b} → "a,\\ b"  (тоже не поддерживается mathtext)
    s = _expand_braced_macro(s, "\\cases{", separator="&")

    # 8. Русифицированные имена функций → стандартные
    #    Например, tg{(x)} → \tan{(x)}. Делаем регексом, чтобы не зацепить
    #    случайные части других слов (например, "tangent" не должно стать "\tanent").
    for bare, cmd in _BARE_TO_STANDARD:
        # Заменяем только если перед именем нет \ (т.е. это не уже-команда)
        # и после имени идёт не буква/цифра (т.е. слово закончилось).
        pattern = r"(?<!\\)\b" + re.escape(bare) + r"\b"
        replacement = cmd.replace("\\", "\\\\")
        s = re.sub(pattern, replacement, s)

    return s


def _expand_braced_macro(s: str, opener: str, separator: str = r"\\") -> str:
    """
    Развернуть \\matrix{a\\b\\c} или \\cases{a & b} в обычный текст,
    разделённый запятыми. Использует подсчёт скобок для корректной работы
    с вложенными конструкциями \\sin{...}, \\frac{...}{...}.

    opener: то, что ищем, включая открывающую { ("\\matrix{").
    separator: что разделяет строки внутри ("\\\\" или "&").
    """
    if opener not in s:
        return s

    result = []
    i = 0
    while i < len(s):
        pos = s.find(opener, i)
        if pos == -1:
            result.append(s[i:])
            break
        result.append(s[i:pos])
        # Ищем парную }, учитывая вложенность
        start = pos + len(opener)
        depth = 1
        j = start
        while j < len(s) and depth > 0:
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
            j += 1
        content = s[start:j - 1]
        # Разбиваем по разделителю
        if separator == r"\\":
            parts = re.split(r"\\\\", content)
        else:
            parts = content.split(separator)
        parts = [p.strip().rstrip("\\").strip() for p in parts]
        parts = [p for p in parts if p]
        result.append(",\\ ".join(parts))
        i = j

    return "".join(result)


# ============================================================
# 2. Подготовка LaTeX для Word OMath
# ============================================================
#
# Word через OMaths.BuildUp() умеет читать LaTeX, но со своими ограничениями:
#   - не любит \\left/\\right в режиме BuildUp (выбрасывает их сам)
#   - падает с ошибкой -2147467263 если есть ^ { или _ { (пробел)
#   - предпочитает "школьную" нотацию tg/arctg вместо \\tan/\\arctan
#
# Эти правила взяты из оригинального clean_latex_for_word.

# Соответствие "стандартный LaTeX" → "школьное имя", которое Word отрендерит
# как обычный текст без попытки превратить в красивую функцию (что важно
# для tg/ctg/arctg, которых в стандартном Word OMath нет).
_STANDARD_TO_RUS = [
    (r"\arctan", "arctg"),
    (r"\arcsin", "arcsin"),
    (r"\arccos", "arccos"),
    (r"\tan",    "tg"),
    (r"\cot",    "ctg"),
    (r"\sinh",   "sh"),
    (r"\cosh",   "ch"),
    (r"\tanh",   "th"),
]


def for_word_omath(latex: str) -> str:
    """
    Подготовить LaTeX для вставки через win32com OMaths.BuildUp().

    На входе принимаем любую форму (канонизация будет применена внутри).
    На выходе — строка, которую можно передать в `selection.TypeText`
    после `selection.OMaths.Add(selection.Range)`.
    """
    # Сначала канонизуем — приводим к стандартному виду
    s = canonical_latex(latex)

    # Убираем \left и \right — Word OMath не любит их в BuildUp
    s = s.replace(r"\left", "").replace(r"\right", "")

    # Конвертим обратно \tan → tg для русской нотации в учебнике
    for cmd, school in _STANDARD_TO_RUS:
        s = s.replace(cmd, school)

    # Дополнительный фикс: \log в матане традиционно ln
    s = s.replace(r"\log", "ln")

    return s.strip()
