"""
Адаптер визуального графа — калька с FisicConstructorGenerator.

Один GraphConstructorGenerator обслуживает раздел типа «граф» (constracted=4):
раздел хранит описание графа в generation_parametrs, адаптер исполняет его
и возвращает Task. Движок (core.graph) делает всю работу.

Регистрация в bootstrap — задача Фазы 1; здесь только сам генератор.
"""

from __future__ import annotations
import json

from core import CHECKABLE_DEFAULT, STATIC_DEFAULT, Task, TaskGenerator
from core.graph import isolation


class GraphConstructorGenerator(TaskGenerator):
    """Универсальный генератор для разделов-графов из БД."""

    name = "Визуальный граф"
    capabilities = STATIC_DEFAULT

    def __init__(self, partition_id: int, name: str, config: "str | dict"):
        self.partition_id = partition_id
        self.name = name
        self._raw = self._to_raw(config)
        self.capabilities = self._capabilities()

    def configure(self, params: dict) -> None:
        """Обновить описание графа из БД (зовётся реестром при выдаче)."""
        if not params:
            return
        self._raw = self._to_raw(params["raw"] if "raw" in params else params)
        self.capabilities = self._capabilities()

    def _capabilities(self):
        """
        CHECKABLE — свойство КОНКРЕТНОГО графа, а не класса генератора.

        Один и тот же класс обслуживает все графы сразу, и объявить его
        проверяемым целиком нельзя: граф на `static_task` отдаёт
        отрендеренные блоки, проверять в них нечего. Витрина же должна
        ответить ДО генерации — по ней фронт выбирает экран, — поэтому
        читаем объявление, а не результат.

        Смотрим на объявленные слоты финального узла, а не исполняем
        граф: исполнение стоит запуска рабочего процесса и даёт лишь
        ОДИН случайный вариант, тогда как слоты у графа фиксированы.
        """
        for node in self._raw.get("nodes") or []:
            if not isinstance(node, dict) or node.get("type") != "task":
                continue
            slots = (node.get("params") or {}).get("slots") or []
            if any(str(s).strip() for s in slots):
                return CHECKABLE_DEFAULT
        return STATIC_DEFAULT

    def generate(self) -> Task:
        """
        Исполнить граф.

        Исполнение уезжает в отдельный процесс без доступа к БД (§9
        плана): граф — пользовательский контент, а с пакетами узлов
        буквально сторонний Python, и раньше он получал и процесс
        сервиса, и соединение с базой.

        Исполнитель здесь больше не кэшируется. Кэшировалась сборка и
        валидация — сотые доли миллисекунды на фоне того, что процесс
        живёт между запросами и разбирает граф у себя. Держать вторую
        копию исполнителя в процессе сервиса значило бы вернуть туда то,
        от чего изолируемся.
        """
        return isolation.run_graph(self._raw)

    @staticmethod
    def _to_raw(config: "str | dict") -> dict:
        """
        Описание графа как СЛОВАРЬ, а не разобранный GraphSpec.

        Через границу процесса едет словарь, и разбирать его на этой
        стороне значило бы делать работу дважды — второй раз в процессе,
        который специально ничего не должен исполнять.
        """
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (json.JSONDecodeError, TypeError):
                config = {}
        return dict(config) if isinstance(config, dict) else {}


# ---------- Пример графа (физика v*t, для ручного запуска) ----------

# Пример по умолчанию — нарочно простой, на новых «умных» узлах: формула сама
# заводит входы v,t по своей записи; финальный узел «Задание» принимает текст
# условия с маркерами #имя# и значение ответа прямо в слот — узлы «Текст» на
# условие и на ответ больше не нужны.
#
# Счёт: тринадцать узлов в первой версии языка, шесть после «умных» узлов,
# четыре сейчас. Причём это задание ещё и проверяемое: слот объявил
# размерность, и `task.is_checkable` — True, чего в шестиузловой версии не
# было вовсе.
EXAMPLE_GRAPH = {
    "version": 1,
    "nodes": [
        {"id": "v",    "type": "random_natural", "params": {"min": 1, "max": 50}},
        {"id": "t",    "type": "random_natural", "params": {"min": 1, "max": 50}},
        {"id": "f",    "type": "formula",        "params": {"expr": "v * t"}},
        {"id": "task", "type": "task", "params": {
            "statement": "Пройдено #v# м за #t# с. Найдите путь.",
            "slots": ["s:number:unit=м:label=S"],
        }},
    ],
    "edges": [
        {"from": "v:out", "to": "f:v"},
        {"from": "t:out", "to": "f:t"},
        {"from": "v:out", "to": "task:v"},
        {"from": "t:out", "to": "task:t"},
        {"from": "f:out", "to": "task:s"},
    ],
    "meta": {"max_attempts": 100, "seed": None},
}


# Ещё проще — всё задание в одном узле (для палитры «Готовые задания»).
EXAMPLE_SIMPLE_TASK = {
    "version": 1,
    "nodes": [
        {"id": "task", "type": "simple_task", "params": {
            "variables": ["v:1:50", "t:1:50"],
            "statement": "Пройдено #v# м за #t# с. Найдите путь.",
            "answer_formula": "v * t",
            "answer": "S = #result# м",
        }},
    ],
    "edges": [],
    "meta": {"max_attempts": 100, "seed": None},
}


if __name__ == "__main__":
    gen = GraphConstructorGenerator(partition_id=0, name="demo", config=EXAMPLE_GRAPH)
    task = gen.generate()
    print("Условие:", task.statement[0].render_plain())
    print("Ответ:  ", task.answer[0].render_plain())
