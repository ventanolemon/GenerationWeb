"""
core/latex.py — единая обработка LaTeX перед рендерингом.

Скопирован из десктоп-репо без изменений. Без Qt-зависимостей,
безопасно импортируется в headless-окружении.
"""

from __future__ import annotations
import re


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
    s = latex
    s = s.replace("^ {", "^{").replace("^  {", "^{")
    s = s.replace("_ {", "_{").replace("_  {", "_{")
    s = s.replace(r"\,", " ").replace(r"\;", " ").replace(r"\quad", " ")
    s = re.sub(r"\\mathrm\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\mathit\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\text\{([^}]*)\}", r"\\mathrm{\1}", s)
    s = s.replace(r"\operatorname{atan}", r"\arctan")
    s = s.replace(r"\operatorname{asin}", r"\arcsin")
    s = s.replace(r"\operatorname{acos}", r"\arccos")
    s = s.replace(r"\operatorname{actg}", r"\operatorname{arccot}")
    s = _expand_braced_macro(s, "\\matrix{")
    s = _expand_braced_macro(s, "\\cases{", separator="&")
    for bare, cmd in _BARE_TO_STANDARD:
        pattern = r"(?<!\\)\b" + re.escape(bare) + r"\b"
        replacement = cmd.replace("\\", "\\\\")
        s = re.sub(pattern, replacement, s)
    return s


def _expand_braced_macro(s: str, opener: str, separator: str = r"\\") -> str:
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
        if separator == r"\\":
            parts = re.split(r"\\\\", content)
        else:
            parts = content.split(separator)
        parts = [p.strip().rstrip("\\").strip() for p in parts]
        parts = [p for p in parts if p]
        result.append(",\\ ".join(parts))
        i = j
    return "".join(result)


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
    s = canonical_latex(latex)
    s = s.replace(r"\left", "").replace(r"\right", "")
    for cmd, school in _STANDARD_TO_RUS:
        s = s.replace(cmd, school)
    s = s.replace(r"\log", "ln")
    return s.strip()
