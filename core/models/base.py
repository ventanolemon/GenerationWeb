"""
Контракт модели.

Определение взято из docs/architecture/models_on_july.md, §4 — и выведено
оно из того, чем четыре существующих модуля (линал, ОПВС, английский,
информатика) УЖЕ являются, а не придумано сверху:

    Модель — питоновский модуль, который по зерну строит ЭКЗЕМПЛЯР
    предметной ситуации и отдаёт из него ИМЕНОВАННЫЕ ТИПИЗИРОВАННЫЕ
    величины. Модель не знает, какое задание из неё соберут.

Последнее — главное отличие от сегодняшнего `get_exercise()`, который
решает сразу всё: что показать, что спросить и как это выглядит. Отсюда и
берётся текстовый ком, в котором двенадцать величин склеены в строку, а
неверная среди них живёт до тех пор, пока кто-нибудь не пересчитает ответ
руками (§2.1 — так и оказалось).

Модель отвечает только на вопрос «что здесь есть»: матрица, её
собственные значения, характеристический многочлен. Каким заданием это
станет — решает разводка проводов в графе: часть величин уходит в
`#маркеры#` условия, часть — в слоты ответа. Прямое следствие, замеченное
на ОПВС: «схема по функции» и «функция по схеме» — это ОДНА модель с
разной разводкой, а не два генератора.

Границы (§4.3): модель не решает, какое это задание; не форматирует
ответ; не ходит в БД и в сеть; не печатает.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

#: Величины этих типов лежат в `Instance.blocks`, остальные — в `values`.
#: Разделение не техническое: `values` — это то, ЧТО в ситуации есть
#: (проверяемое, подставляемое в условие), а `blocks` — то, как её
#: ПОКАЗАТЬ. Смешать их значило бы снова свалить смысл и оформление в одну
#: кучу, с чего вся эта работа и началась.
BLOCK_TYPES = ("block", "block_list", "image")

#: Типы величин, которые модель имеет право объявлять.
#:
#: Список повторяет значения PortType, но НЕ импортирует его: `core.models`
#: не должен зависеть от `core.graph` (см. Output.type о том, почему автор
#: модели не тянет к себе внутренности графа). Первая же попытка сослаться
#: отсюда на PortType дала цикл импорта — core.graph тянет узлы, узлы тянут
#: модели, — и реестр моделей успевал построиться пустым. Совпадение
#: словаря с PortType сторожит тест (core/test_models.py).
#:
#: Двух типов здесь нет намеренно:
#:   * `task` — модель не собирает задание, это граница §4.3;
#:   * `any` — величина без типа отменяет то, ради чего OUTPUTS заводился.
VALUE_TYPES = frozenset({
    "number", "string", "bool", "list", "expr", "matrix", "number_dict",
    "words", "sentences", "func",
})
OUTPUT_TYPES = VALUE_TYPES | frozenset(BLOCK_TYPES)


class ModelError(Exception):
    """
    Модели не повезло: на этом зерне экземпляр не сложился.

    Отдельный тип, а не голый ValueError: узел превращает его в
    RetryGeneration — «перебрось зерно и попробуй ещё», — а не в поломку
    графа. Именно так ведут себя все стохастические источники в языке.
    """


class ModelConfigError(ModelError):
    """
    Параметры модели противоречивы — перебрасывать зерно бессмысленно.

    Различать это с невезением обязательно. «Различных собственных
    значений нужно 4, а в диапазоне [0, 2] их три» — не неудачный бросок,
    а ошибка автора графа: сколько ни повторяй, не сложится. Если бы такое
    ехало как RetryGeneration, исполнитель молча сделал бы двести попыток
    и сообщил бы про исчерпанные попытки — то есть спрятал бы настоящую
    причину за симптомом. Узел превращает эту ошибку в
    GraphValidationError и показывает автору сразу, при правке формы.
    """


@dataclass(frozen=True)
class Output:
    """
    Одна величина, которую модель обещает отдать.

    `type` — строка, совпадающая со значением PortType ("number", "matrix",
    "expr", "list", …). Строкой, а не самим PortType, сознательно: автор
    модели пишет предметный модуль и не должен тянуть в него внутренности
    графа. Проверку и перевод в PortType делает узел — там, где графу и
    место.
    """

    name: str
    type: str
    title: str = ""          # подпись порта для автора графа
    description: str = ""

    @property
    def is_block(self) -> bool:
        return self.type in BLOCK_TYPES


@dataclass
class Instance:
    """
    Экземпляр предметной ситуации: конкретная матрица, конкретная схема.

    `params` хранится вместе с величинами намеренно: при разборе жалобы
    «задание собралось странным» нужно знать, чем модель крутили, а не
    только что получилось.
    """

    values: dict[str, Any] = field(default_factory=dict)
    blocks: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Any:
        """Величина по имени — неважно, в какой из двух корзин она лежит."""
        if name in self.values:
            return self.values[name]
        if name in self.blocks:
            return self.blocks[name]
        raise KeyError(name)

    def has(self, name: str) -> bool:
        return name in self.values or name in self.blocks

    def equivalent(self, name: str, answer: Any) -> bool:
        """
        Совпадает ли ответ с величиной `name` ПО СУЩЕСТВУ.

        Зачем отдельная ручка, когда в проекте есть полноценная проверка
        ответов (`core.answers`: NumberSpec, ExpressionSpec, SlotsSpec):
        та проверка знает про допуски, опечатки и единицы измерения, но
        не знает предметных эквивалентностей. Собственный вектор задан с
        точностью до множителя; булева функция — с точностью до формы
        записи; базис — с точностью до замены. Это знание есть только у
        модели, и держать его больше негде.

        Состояние на сегодня: ручка объявлена, реализована и покрыта
        тестами, но конвейер проверки ответов её ЕЩЁ НЕ СПРАШИВАЕТ —
        первым потребителем станет перевод логических схем ОПВС на
        стандарт (§5, пункт 2), где сравнение по `sympy_expr` и есть вся
        суть проверки. До тех пор это объявленная возможность с известным
        потребителем, а не задел «на всякий случай».
        """
        return values_equivalent(self.get(name), answer)


def values_equivalent(expected: Any, answer: Any) -> bool:
    """
    Сравнение величин по существу — поведение `equivalent` по умолчанию.

    * списки и кортежи сравниваются КАК МУЛЬТИМНОЖЕСТВА: порядок, в
      котором перечислены собственные значения, не является частью
      ответа, а кратность — является;
    * числа и символьные выражения — через `simplify(a - b) == 0`, иначе
      `1/2` и `0.5` считались бы разными ответами;
    * всё остальное — сравнением строк после нормализации пробелов.

    Модель переопределяет там, где этого мало.
    """
    if isinstance(expected, (list, tuple)) or isinstance(answer, (list, tuple)):
        left = list(expected) if isinstance(expected, (list, tuple)) else [expected]
        right = list(answer) if isinstance(answer, (list, tuple)) else [answer]
        return _same_multiset(left, right)
    return _same_value(expected, answer)


def _same_multiset(left: Iterable, right: Iterable) -> bool:
    """
    Совпадают ли два набора величин с точностью до порядка.

    Жадное сопоставление, а не сортировка: сравнивать приходится
    символьные выражения, у которых нет порядка, но есть равенство.
    Наборы здесь короткие (собственные значения матрицы 2×4), поэтому
    квадратичность не имеет значения.
    """
    rest = list(right)
    left = list(left)
    if len(left) != len(rest):
        return False
    for item in left:
        for i, candidate in enumerate(rest):
            if _same_value(item, candidate):
                del rest[i]
                break
        else:
            return False
    return True


def _same_value(expected: Any, answer: Any) -> bool:
    """Одна величина: сначала символьно, при неудаче — строкой."""
    try:
        import sympy as sp

        left = sp.sympify(expected) if not isinstance(expected, sp.Basic) else expected
        right = sp.sympify(answer) if not isinstance(answer, sp.Basic) else answer
        if isinstance(left, sp.MatrixBase) or isinstance(right, sp.MatrixBase):
            if not (isinstance(left, sp.MatrixBase)
                    and isinstance(right, sp.MatrixBase)):
                return False
            if left.shape != right.shape:
                return False
            return all(sp.simplify(a - b) == 0 for a, b in zip(left, right))
        return bool(sp.simplify(left - right) == 0)
    except Exception:
        # Не всё сравнимое символьно: строки, булевы формулы, имена.
        return _text(expected) == _text(answer)


def _text(value: Any) -> str:
    return " ".join(str(value).split())


class Model:
    """
    База модели. Наследник объявляет `OUTPUTS`, `PARAMS` и пишет `build`.

    Класс, а не голый модуль с функциями: реестру нужен один способ
    спросить у модели имя, параметры и величины, а автору — место, куда
    положить вспомогательные методы, не засоряя пространство модуля.
    Модуль при этом остаётся единицей поставки: один файл — одна модель
    (или несколько родственных).
    """

    #: Идентификатор латиницей: из него собирается type_id узла.
    name: str = ""
    #: Как модель называется в палитре редактора.
    title: str = ""
    description: str = ""
    #: Категория узла — та же, что у остальных узлов предметной области
    #: (linalg, image, informatics…), чтобы модель встала в палитру рядом
    #: с операциями своего предмета, а не в отдельный чулан «модели».
    category: str = ""
    #: Объявление величин. По нему строятся выходные порты узла.
    OUTPUTS: list[Output] = []
    #: Схема параметров — той же формы, что PARAMS_SCHEMA узла, потому что
    #: это она и есть: редактор рисует форму по ней, ничего не зная о
    #: моделях.
    PARAMS: dict = {}

    def build(self, rng, **params) -> Instance:
        """По зерну и параметрам построить экземпляр. Переопределяется."""
        raise NotImplementedError

    def normalize_params(self, params: dict) -> dict:
        """
        Проверить и привести параметры; на противоречивых — ModelConfigError.

        Отдельный метод, а не проверка внутри build, потому что у него два
        вызывающих: сам build и узел — при правке формы в редакторе. Автор
        графа узнаёт о противоречии, когда его допустил, а не когда
        двести попыток генерации закончились ничем.
        """
        return dict(params)

    # --- служебное ---

    def output(self, name: str) -> Output:
        for out in self.OUTPUTS:
            if out.name == name:
                return out
        raise KeyError(name)

    def output_names(self) -> list[str]:
        return [o.name for o in self.OUTPUTS]

    def check_instance(self, instance: Instance) -> None:
        """
        Проверить, что экземпляр действительно содержит обещанное.

        Вызывается узлом после build(). Модель, забывшая положить
        объявленную величину, должна падать внятно и сразу, а не отдавать
        None в провод, где он всплывёт через три узла чем-нибудь вроде
        «NoneType не поддерживает вычитание».
        """
        missing = [o.name for o in self.OUTPUTS if not instance.has(o.name)]
        if missing:
            raise ModelError(
                f"модель {self.name!r} объявила величины, которых нет в "
                f"экземпляре: {', '.join(sorted(missing))}"
            )
        for out in self.OUTPUTS:
            here = instance.blocks if out.is_block else instance.values
            if out.name not in here:
                where = "blocks" if out.is_block else "values"
                raise ModelError(
                    f"модель {self.name!r}: величина {out.name!r} объявлена "
                    f"как {out.type!r} и должна лежать в Instance.{where}"
                )
