"""
Модель: программа на C и внесённые в неё ошибки.

Третья модель по стандарту (§5, пункт 3) — и взята она именно третьей
затем, чтобы проверить стандарт на НЕПОХОЖЕМ материале. У спектра
величины числовые, у схемы символьные, здесь — текст программы, её вывод
и список правок. Если стандарт держится и на этом, он описывает не три
частных случая, а общее.

Что было. `CCodeMistakesGenerator` собирает задание «найдите ошибки» и
кладёт в ответ четыре текстовых блока: исправный код, ожидаемый вывод,
подпись «Список ошибок:» и сами ошибки одной строкой с буллитами.
Проверить нельзя ничего — как и в двух предыдущих разборах, ответ
существует оформлением.

Что стало. Величины: `code` (исправный текст), `broken` (то, что видит
студент), `output` (что напечатает программа), `mistakes` (описания),
`lines` (номера изменённых строк), `kind` (вид программы). Отсюда
собираются проверяемые задания: «что напечатает программа» — ответ
строкой, «в каких строках изменён код» — ответ списком чисел.

Инвариант, которого у генератора не было: **на одну строку приходится не
больше одной правки**. Без него «допущено 5 ошибок» и «5 строк с
ошибками» расходятся — замер показал 43% прогонов, где две правки легли
в одну строку, — и задание «укажите номера строк» становится
неформулируемым. Модель добивается этого пересборкой, а не правкой
генератора: у старого генератора свой договор с существующими заданиями.
"""

from __future__ import annotations

import random
import re

from .base import Instance, Model, ModelConfigError, ModelError, Output

KINDS = ("linear", "conditional", "loop")
ANY_KIND = "любой"

_LINE = re.compile(r"^line (-?\d+):")


class CCodeInstance(Instance):
    """Экземпляр, знающий, что вывод программы сравнивают построчно."""

    def equivalent(self, name: str, answer) -> bool:
        if name != "output":
            return super().equivalent(name, answer)
        from ..program_output import same_output

        return same_output(self.values["output"], answer)


class CCodeModel(Model):
    """Программа на C с внесёнными синтаксическими ошибками."""

    name = "opvs_ccode"
    title = "Программа на C с ошибками"
    description = (
        "Короткая программа на C, её вывод и внесённые в неё "
        "синтаксические ошибки — величинами, а не текстом ответа. Отсюда "
        "собираются «что напечатает программа» и «в каких строках "
        "изменён код»."
    )
    category = "informatics"

    OUTPUTS = [
        Output("broken", "string", "Код с ошибками",
               "То, что показывают студенту."),
        Output("code", "string", "Исправный код",
               "Программа до внесения ошибок."),
        Output("output", "string", "Вывод программы",
               "Что печатает ИСПРАВНАЯ программа."),
        Output("mistakes", "list", "Ошибки",
               "По одному описанию на правку, в порядке строк."),
        Output("lines", "list", "Строки с ошибками",
               "Номера изменённых строк по возрастанию, без повторов."),
        Output("mistake_count", "number", "Сколько ошибок",
               "Совпадает с длиной обоих списков."),
        Output("kind", "string", "Вид программы",
               "linear, conditional или loop."),
    ]

    PARAMS = {
        "mistakes": {"type": "int", "default": 5},
        "kind": {"type": "enum", "values": [ANY_KIND, *KINDS],
                 "default": ANY_KIND, "optional": True},
    }

    def normalize_params(self, params: dict) -> dict:
        try:
            count = int(params.get("mistakes", 5))
        except (TypeError, ValueError):
            raise ModelConfigError("mistakes должно быть целым числом.")
        if not 1 <= count <= 8:
            # Восемь — столько разных порч умеет генератор; просить больше
            # значит просить повторов, а повтор на одной строке ломает
            # инвариант «одна правка на строку».
            raise ModelConfigError("ошибок должно быть от 1 до 8.")
        kind = str(params.get("kind", ANY_KIND) or ANY_KIND)
        if kind not in (ANY_KIND, *KINDS):
            raise ModelConfigError(
                f"вид программы {kind!r} неизвестен; допустимы "
                f"{', '.join((ANY_KIND, *KINDS))}.")
        return {"mistakes": count, "kind": kind}

    def build(self, rng, **params) -> Instance:
        cfg = self.normalize_params(params)

        for _ in range(40):
            attempt = self._attempt(rng, cfg)
            if attempt is not None:
                return attempt
        raise ModelError(
            "не удалось внести ошибки так, чтобы каждая попала в свою "
            "строку — попробуйте уменьшить их число.")

    def _attempt(self, rng, cfg: dict):
        """
        Одна попытка. None — правки столкнулись на одной строке.

        Пересборка целиком, а не подгонка: порча необратима (генератор
        меняет строки на месте), и «снять лишнюю правку» уже нельзя.
        """
        from exercises.opvs.opvs_new import CCodeGenerator

        state = random.getstate()
        random.seed(rng.getrandbits(64))
        try:
            generator = CCodeGenerator()
            kind = None if cfg["kind"] == ANY_KIND else cfg["kind"]
            generator.generate_code(kind)
            code = str(generator)
            output = generator.get_expected_output()
            mistakes = list(generator.introduce_mistakes(cfg["mistakes"]))
            broken = str(generator)
            code_type = generator.code_type
        except (ValueError, IndexError) as e:
            raise ModelError(f"генератор кода не справился: {e}")
        finally:
            # Глобальный random сеет исполнитель графа, один раз на
            # попытку. Оставить его сбитым значило бы менять результат
            # соседних узлов.
            random.setstate(state)

        numbers = [_line_number(text) for text in mistakes]
        if None in numbers or len(set(numbers)) != len(numbers):
            return None

        order = sorted(range(len(mistakes)), key=lambda i: numbers[i])
        return CCodeInstance(
            values={
                "broken": broken,
                "code": code,
                "output": output,
                "mistakes": [mistakes[i] for i in order],
                "lines": [numbers[i] for i in order],
                "mistake_count": len(mistakes),
                "kind": str(code_type),
            },
            params=dict(cfg),
        )


def _line_number(text: str):
    """Номер строки из записи журнала «line N: …». None — записи нет."""
    match = _LINE.match(str(text))
    return int(match.group(1)) if match else None


MODEL = CCodeModel()
