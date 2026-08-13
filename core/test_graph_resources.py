"""
Поставочные ресурсы: файл по идентификатору вместо пути.

Проверяется не «функция возвращает путь», а свойство, ради которого всё
и затевалось: граф с файлом ПЕРЕЖИВАЕТ переезд на другую машину. Замер до
правки — граф, собранный на десктопе, на сервере падал «файл со словами
не найден», потому что путь машинно-локален по своей природе.

Отдельно — граница: идентификатор приезжает по синку от чужой установки,
и «прочитать любой файл, до которого дотянется процесс» не та
возможность, которую стоит давать значению в JSON.

Запуск:
    python -m unittest core.test_graph_resources
"""

from __future__ import annotations

import unittest

from core.graph import resources as R
from core.graph.errors import GraphValidationError
from core.graph.executor import GraphExecutor
from core.graph.nodes import DEFAULT_REGISTRY
from core.graph.spec import GraphSpec


def _some_dictionary() -> str:
    """
    Идентификатор ЛЮБОГО поставочного словаря.

    Не прибитое имя файла: состав поставки у сервера и десктопа разный
    (у десктопа словарей меньше), и тест с конкретным именем проходил бы
    на одной стороне и падал на другой, ничего не сообщая по существу.
    Проверяется свойство «поставочный файл открывается», а не наличие
    конкретного словаря.
    """
    words = R.available(["words"])
    if not words:
        raise unittest.SkipTest("в этой поставке нет словарей")
    return words[0].id


class ResolveTests(unittest.TestCase):

    def test_identifier_resolves_inside_the_shipped_folder(self):
        path = R.resolve(_some_dictionary())
        self.assertTrue(path.is_relative_to(R.RESOURCES_DIR.resolve()))

    def test_plain_path_stays_itself(self):
        # Свои файлы на десктопе никуда не делись: запретить путь значило
        # бы сломать существующие графы ради красоты.
        self.assertEqual(str(R.resolve("/home/teacher/w.json")),
                         "/home/teacher/w.json")

    def test_windows_path_is_not_mistaken_for_an_identifier(self):
        # Двоеточие есть и в пути Windows — приставка различается по тому,
        # что стоит ПЕРЕД ним, а не по наличию двоеточия.
        raw = r"C:\Users\teacher\words.json"
        self.assertFalse(R.is_resource_id(raw))
        self.assertEqual(str(R.resolve(raw)), raw)

    def test_escaping_the_shipped_folder_is_refused(self):
        for bad in ("res:../const.py", "res:../../etc/passwd",
                    "res:words/../../const.py", "res:/etc/passwd"):
            with self.subTest(value=bad):
                with self.assertRaises(GraphValidationError):
                    R.resolve(bad)

    def test_empty_identifier_is_refused(self):
        with self.assertRaises(GraphValidationError):
            R.resolve("res:")

    def test_refusal_does_not_silently_fix_the_value(self):
        """
        Молча срезать `..` нельзя: исправленный идентификатор укажет не
        туда, куда просили, и разбираться будут с загадкой, а не с
        отказом.
        """
        with self.assertRaises(GraphValidationError) as ctx:
            R.resolve("res:../const.py")
        self.assertIn("res:../const.py", str(ctx.exception))


class ListingTests(unittest.TestCase):

    def test_shipped_dictionaries_are_listed(self):
        self.assertTrue(R.available(["words"]))

    def test_every_listed_id_resolves_to_an_existing_file(self):
        # Список показывают человеку как «что можно выбрать»; пункт,
        # который не открывается, хуже отсутствующего.
        for res in R.available():
            with self.subTest(id=res.id):
                self.assertTrue(R.resolve(res.id).is_file())

    def test_words_and_sentences_are_separated_by_content(self):
        """
        Лежат в одной папке и различаются содержимым. Не разделив их,
        автору предложат словарь там, где нужен набор предложений, — и
        узел упадёт уже при выдаче задания.
        """
        words = {r.id for r in R.available(["words"])}
        sentences = {r.id for r in R.available(["sentences"])}
        self.assertTrue(sentences)
        self.assertFalse(words & sentences)

    def test_unknown_kind_is_not_an_error(self):
        self.assertEqual(R.available(["чепуха"]), [])

    def test_listing_is_stable(self):
        # Порядок показывают человеку: прыгающий список — это список, в
        # котором не найти вчерашний пункт.
        self.assertEqual([r.id for r in R.available()],
                         [r.id for r in R.available()])


class SchemaTests(unittest.TestCase):

    def test_every_file_param_declares_its_resource_kind(self):
        """
        Инспектор отбирает список по `resource` из СХЕМЫ, а не по типу
        узла. Файловый параметр без вида остался бы без выбора из
        поставки — то есть с прежним «путь, который работает на одной
        машине», и молча.
        """
        missing = []
        for cls in DEFAULT_REGISTRY:
            for name, meta in (cls.PARAMS_SCHEMA or {}).items():
                if isinstance(meta, dict) and meta.get("type") == "file":
                    if meta.get("resource") not in R.KINDS:
                        missing.append(f"{cls.type_id}.{name}")
        self.assertEqual(missing, [])


class EndToEndTests(unittest.TestCase):
    """Главное: граф с поставочным файлом исполняется здесь и сейчас."""

    def _pool_graph(self, file_value: str) -> dict:
        return {
            "version": 1,
            "nodes": [
                {"id": "src", "type": "pool",
                 "params": {"columns": ["a", "b"], "file": file_value}},
                {"id": "pick", "type": "pool_pick",
                 "params": {"columns": ["a", "b"]}},
                {"id": "fin", "type": "task",
                 "params": {"statement": "Переведите #a#",
                            "slots": ["x:text"]}},
            ],
            "edges": [
                {"from": "src:out", "to": "pick:in"},
                {"from": "pick:a", "to": "fin:a"},
                {"from": "pick:b", "to": "fin:x"},
            ],
            "meta": {"seed": 3},
        }

    def test_graph_with_a_shipped_file_runs(self):
        task = GraphExecutor(GraphSpec.parse(
            self._pool_graph(_some_dictionary()))).run()
        self.assertTrue("".join(b.render_plain() for b in task.statement))

    def test_graph_escaping_the_folder_refuses_to_run(self):
        with self.assertRaises(GraphValidationError):
            GraphExecutor(GraphSpec.parse(
                self._pool_graph("res:../const.py"))).run()

    def test_foreign_path_still_says_what_is_wrong(self):
        """
        Путь с чужой машины остаётся ошибкой — но НАЗВАННОЙ. Именно она и
        была замером: граф с десктопа падал на сервере, и по сообщению
        было видно, что путь чужой.
        """
        with self.assertRaises(GraphValidationError) as ctx:
            GraphExecutor(GraphSpec.parse(
                self._pool_graph("/home/teacher/pool.json"))).run()
        self.assertIn("/home/teacher/pool.json", str(ctx.exception))

    def test_identifier_appears_in_the_error_without_quotes_of_a_path(self):
        # Сообщение должно называть то, что написал автор: идентификатор,
        # а не разрешённый путь внутри поставки, которого он не писал.
        with self.assertRaises(GraphValidationError) as ctx:
            GraphExecutor(GraphSpec.parse(
                self._pool_graph("res:words/нет-такого.json"))).run()
        self.assertIn("res:words/нет-такого.json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
