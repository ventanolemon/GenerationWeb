"""
Булева формула, записанная человеком: чтение, запись, равенство функций.

Нужно для проверки ответа: «выпишите функцию по схеме» имеет бесконечно
много правильных записей — `not(A) v (B ^ C)`, `¬A ∨ BC`, `!A + B*C`, — и
все они одна и та же функция. Сравнивать такие ответы строкой бесполезно;
сравнивать надо функции, а для этого запись сначала нужно прочитать.

Модуль лежит в `core`, а не в `core/models` или в `core/answers`, потому
что нужен обоим и ни одному не принадлежит: модель отдаёт функцию,
проверка ответа её сравнивает, и понятие «та же функция» у них обязано
быть ОДНО. Две реализации разошлись бы, и разошлись бы молча — приняв у
студента то, что модель считает другим ответом.

Почему свой разборщик, а не `sympify`. Во-первых, `sympify` исполняет
питоновский код — на ответе студента это недопустимо. Во-вторых, он
читает привычную запись НЕВЕРНО и молча: `^` в питоне — исключающее ИЛИ, а
в наших схемах и в учебнике — конъюнкция; `v` он примет за переменную, а
не за дизъюнкцию. Молча неверный разбор хуже отказа: студент получил бы
«неправильно» за правильный ответ.

Принимаются все три обиходные системы обозначений:

    И    ^  &  ∧  *  and  и        (а также соседство: `AB`, `A(B v C)`)
    ИЛИ  v  |  ∨  +  or   или
    НЕ   not  !  ¬  ~  не

Приоритет обычный: НЕ выше И, И выше ИЛИ.
"""

from __future__ import annotations

_AND_WORDS = {"and", "и"}
_OR_WORDS = {"or", "или"}
_NOT_WORDS = {"not", "не"}

_AND_SIGNS = {"^", "&", "∧", "*", "·", "×"}
_OR_SIGNS = {"v", "V", "|", "∨", "+"}
_NOT_SIGNS = {"!", "¬", "~"}


class BooleanTextError(ValueError):
    """Запись не удалось прочитать. Сообщение адресовано человеку."""


def parse_boolean(text: str, variables):
    """
    Текст → выражение sympy над указанными переменными.

    `variables` — имена входов схемы. Список обязателен: он и отличает
    переменную от опечатки. Без него `Q` молча стало бы новым символом, и
    ответ «Q» оказался бы «просто другой функцией», а не ошибкой.
    """
    import sympy as sp

    known = {str(v).lower(): sp.Symbol(str(v)) for v in variables}
    tokens = _tokens(str(text), known)
    if not tokens:
        raise BooleanTextError("пустая запись")
    parser = _Parser(tokens, known, sp)
    value = parser.parse_or()
    if parser.pos != len(tokens):
        raise BooleanTextError(
            f"лишнее в записи начиная с {parser.peek()!r}")
    return value


def _tokens(text: str, known: dict) -> list:
    """
    Разбор на лексемы: ('var', имя) | ('and',) | ('or',) | ('not',) | ('(',) | (')',).

    Слово, которого нет среди переменных и операторов, разбирается по
    буквам, если КАЖДАЯ буква — переменная: `ABC` в учебнике означает
    конъюнкцию трёх входов, и отказывать в такой записи было бы
    придирчивостью, а не строгостью.
    """
    out: list = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "()":
            out.append((ch,))
            i += 1
            continue
        if ch in _NOT_SIGNS:
            out.append(("not",))
            i += 1
            continue
        if ch in _AND_SIGNS:
            out.append(("and",))
            i += 1
            continue
        # `v` — и знак дизъюнкции, и потенциальная буква имени, поэтому
        # разбирается ниже вместе со словами; здесь только прочие знаки.
        if ch in _OR_SIGNS and ch not in ("v", "V"):
            out.append(("or",))
            i += 1
            continue
        if ch.isalnum() or ch == "_":
            start = i
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            out.extend(_word(text[start:i], known))
            continue
        raise BooleanTextError(f"непонятный знак {ch!r}")
    return out


def _word(word: str, known: dict) -> list:
    low = word.lower()
    if low in known:
        return [("var", low)]
    if low in _AND_WORDS:
        return [("and",)]
    if low in _OR_WORDS:
        return [("or",)]
    if low in _NOT_WORDS:
        return [("not",)]
    if low in ("v",):
        return [("or",)]
    if len(word) > 1 and all(ch.lower() in known for ch in word):
        return [("var", ch.lower()) for ch in word]
    raise BooleanTextError(
        f"неизвестная переменная {word!r}; в схеме есть "
        f"{', '.join(sorted(v.upper() for v in known))}")


class _Parser:
    """
    Рекурсивный спуск: ИЛИ ← И ← НЕ ← скобки/переменная.

    Соседство означает И (`AB`, `A(B v C)`) — так пишут в учебнике.
    Реализуется тем, что разбор конъюнкции продолжается, пока следующая
    лексема МОЖЕТ начать множитель, а не только по явному знаку.
    """

    STARTERS = {"var", "not", "("}

    def __init__(self, tokens: list, known: dict, sp):
        self.tokens = tokens
        self.known = known
        self.sp = sp
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def parse_or(self):
        value = self.parse_and()
        while self.peek() and self.peek()[0] == "or":
            self.pos += 1
            value = self.sp.Or(value, self.parse_and())
        return value

    def parse_and(self):
        value = self.parse_not()
        while True:
            token = self.peek()
            if token is None:
                break
            if token[0] == "and":
                self.pos += 1
                value = self.sp.And(value, self.parse_not())
            elif token[0] in self.STARTERS:
                value = self.sp.And(value, self.parse_not())
            else:
                break
        return value

    def parse_not(self):
        if self.peek() and self.peek()[0] == "not":
            self.pos += 1
            return self.sp.Not(self.parse_not())
        return self.parse_atom()

    def parse_atom(self):
        token = self.peek()
        if token is None:
            raise BooleanTextError("запись обрывается на середине")
        if token[0] == "var":
            self.pos += 1
            return self.known[token[1]]
        if token[0] == "(":
            self.pos += 1
            value = self.parse_or()
            if not (self.peek() and self.peek()[0] == ")"):
                raise BooleanTextError("не закрыта скобка")
            self.pos += 1
            return value
        raise BooleanTextError(f"здесь ожидалась переменная, а не {token[0]!r}")


def format_boolean(expr) -> str:
    """
    Выражение sympy → запись в обозначениях схемы: `not(A) v (B ^ C)`.

    Нужна, чтобы ключ выглядел так же, как формула под чертежом. Иначе
    ответ, приехавший по проводу выражением, показывался бы в записи
    sympy (`~A | (B & C)`) — верно по смыслу и чуждо по виду для того,
    кто смотрит на схему по ГОСТ.
    """
    import sympy as sp

    if isinstance(expr, sp.Symbol):
        return str(expr)
    if isinstance(expr, sp.logic.boolalg.BooleanTrue):
        return "1"
    if isinstance(expr, sp.logic.boolalg.BooleanFalse):
        return "0"
    if isinstance(expr, sp.Not):
        return f"not({format_boolean(expr.args[0])})"
    if isinstance(expr, sp.And):
        return "(" + " ^ ".join(_sorted_parts(expr)) + ")"
    if isinstance(expr, sp.Or):
        return "(" + " v ".join(_sorted_parts(expr)) + ")"
    return str(expr)


def _sorted_parts(expr) -> list:
    """
    Слагаемые в устойчивом порядке.

    У sympy `And`/`Or` — множества, и порядок аргументов между запусками
    не гарантирован. Ключ, который в двух прогонах выглядит по-разному,
    выглядит сломанным, поэтому порядок задаётся здесь.
    """
    return sorted((format_boolean(arg) for arg in expr.args), key=str)


def boolean_equivalent(expected, answer, variables) -> bool:
    """
    Задают ли две записи ОДНУ функцию.

    Сравнение по существу, а не по форме: `not(A) v (B ^ C)` и `¬A ∨ CB` —
    один ответ. Проверяется через выполнимость исключающего ИЛИ: функции
    равны тогда и только тогда, когда их различие невыполнимо.
    """
    import sympy as sp
    from sympy.logic.boolalg import Xor

    try:
        left = (expected if isinstance(expected, sp.Basic)
                else parse_boolean(expected, variables))
        right = (answer if isinstance(answer, sp.Basic)
                 else parse_boolean(answer, variables))
    except BooleanTextError:
        return False
    unknown = (left.free_symbols | right.free_symbols) - {
        sp.Symbol(str(v)) for v in variables}
    if unknown:
        return False
    return not sp.satisfiable(Xor(left, right))
