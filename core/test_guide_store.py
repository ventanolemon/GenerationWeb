"""
Правка базы знаний из приложения: поверх поставки, теми же правилами.

Три свойства, ради которых всё и сделано именно так
---------------------------------------------------
1. **Поставка остаётся умолчанием.** Пустая таблица — «правок нет», и
   клиент показывает вкомпилированное. Иначе база знаний перестала бы
   открываться без сети, а это единственное, ради чего её вкомпилировали.
2. **Правка проходит ТУ ЖЕ проверку формата**, что и файл в репозитории.
   Набор разметки закрыт; страница с таблицей сломалась бы у всех
   читателей сразу, а автор правки узнал бы последним.
3. **Правит тот, кто отвечает за установку.** Страница одна на всех —
   в отличие от предмета преподавателя, который его собственный.

Запуск:
    python -m unittest core.test_guide_store
"""

from __future__ import annotations

import shutil
import tempfile
import unittest

from core import Repository, guide_store as store


def _repo() -> Repository:
    from const import DB_PATH

    # Поставочную БД открываем на КОПИИ (docs/handbook/05 §10).
    copy = tempfile.mktemp(suffix=".db")
    shutil.copyfile(DB_PATH, copy)
    return Repository(copy)


class ShippedIsTheDefaultTests(unittest.TestCase):
    """Без правок видно ровно поставку."""

    def setUp(self):
        self.repo = _repo()

    def test_an_empty_table_means_no_changes(self):
        self.assertEqual(store.overrides(self.repo), {})

    def test_merged_returns_the_shipped_pages(self):
        pages = store.merged(self.repo)
        self.assertEqual(len(pages), len(store.shipped()))
        self.assertTrue(all(not p["edited"] for p in pages))

    def test_the_order_comes_from_the_shipped_files(self):
        pages = store.merged(self.repo)
        orders = [p["order"] for p in pages]
        self.assertEqual(orders, sorted(orders))

    def test_an_edit_does_not_change_the_order(self):
        """
        `order` объявлен в заголовочном блоке файла. Позволить менять его
        из редактора значило бы завести второй источник порядка.
        """
        pages = store.merged(self.repo)
        last = pages[-1]
        store.save(self.repo, last["id"], title="Переименовано",
                   body=last["body"], actor="dev")
        self.assertEqual([p["id"] for p in store.merged(self.repo)],
                         [p["id"] for p in pages])


class EditingTests(unittest.TestCase):

    def setUp(self):
        self.repo = _repo()
        self.page = store.merged(self.repo)[0]

    def test_a_saved_edit_shows_up_and_is_marked(self):
        store.save(self.repo, self.page["id"], title="Новый заголовок",
                   body="Новый текст.", actor="dev")
        page = store.merged(self.repo)[0]
        self.assertEqual(page["title"], "Новый заголовок")
        self.assertEqual(page["body"], "Новый текст.")
        self.assertTrue(page["edited"])
        self.assertEqual(page["updated_by"], "dev")

    def test_sections_are_recomputed_from_the_new_text(self):
        """
        Оглавление — производное от текста, и хранить его отдельно
        нельзя: разошлось бы с телом при первой же правке.
        """
        store.save(self.repo, self.page["id"], title="Т",
                   body="Абзац.\n\n## Свежий раздел {#fresh}\n\nЕщё.\n",
                   actor="dev")
        page = store.merged(self.repo)[0]
        self.assertEqual([s["id"] for s in page["sections"]], ["fresh"])

    def test_reset_brings_the_shipped_page_back(self):
        original = self.page["title"]
        store.save(self.repo, self.page["id"], title="Временно",
                   body="Текст.", actor="dev")
        self.assertTrue(store.reset(self.repo, self.page["id"]))
        self.assertEqual(store.merged(self.repo)[0]["title"], original)

    def test_resetting_twice_says_there_was_nothing_to_reset(self):
        store.save(self.repo, self.page["id"], title="Т", body="Текст.",
                   actor="dev")
        self.assertTrue(store.reset(self.repo, self.page["id"]))
        self.assertFalse(store.reset(self.repo, self.page["id"]))

    def test_editing_again_after_a_reset_works(self):
        """
        Снятая правка помечается, а не удаляется. Повторное сохранение
        обязано её оживить, а не упереться в первичный ключ.
        """
        page_id = self.page["id"]
        store.save(self.repo, page_id, title="Раз", body="Текст.", actor="dev")
        store.reset(self.repo, page_id)
        store.save(self.repo, page_id, title="Два", body="Текст.", actor="dev")
        self.assertEqual(store.merged(self.repo)[0]["title"], "Два")

    def test_a_page_outside_the_shipped_set_cannot_be_created(self):
        """
        Адрес страницы попадает в чужие материалы и в ссылки `guide:`, а
        реестр адресов лежит в репозитории и проверяется прогоном. Новая
        страница мимо реестра — ссылка, которая ломается молча.
        """
        with self.assertRaises(store.GuideEditError) as caught:
            store.save(self.repo, "выдуманная", title="Т", body="Текст.",
                       actor="dev")
        self.assertIn("нет в поставке", str(caught.exception))

    def test_an_empty_title_is_refused(self):
        with self.assertRaises(store.GuideEditError):
            store.save(self.repo, self.page["id"], title="   ",
                       body="Текст.", actor="dev")


class FormatIsCheckedTests(unittest.TestCase):
    """Та же проверка, что у файлов поставки, и с той же причиной."""

    def setUp(self):
        self.repo = _repo()
        self.page_id = store.merged(self.repo)[0]["id"]

    def _refuses(self, body: str) -> str:
        with self.assertRaises(store.GuideEditError) as caught:
            store.save(self.repo, self.page_id, title="Т", body=body,
                       actor="dev")
        return str(caught.exception)

    def test_a_table_is_refused_with_a_reason_an_author_understands(self):
        message = self._refuses("| а | б |\n")
        self.assertIn("таблиц", message.lower())
        self.assertNotIn("Traceback", message)

    def test_a_heading_without_a_declared_address_is_refused(self):
        message = self._refuses("## Раздел без адреса\n")
        self.assertIn("адрес", message.lower())

    def test_a_link_to_nowhere_is_refused(self):
        message = self._refuses("[туда](guide:nosuchpage)\n")
        self.assertIn("nosuchpage", message)

    def test_a_link_to_a_real_page_is_accepted(self):
        other = [p for p in store.merged(self.repo)
                 if p["id"] != self.page_id][0]
        store.save(self.repo, self.page_id, title="Т",
                   body=f"См. [там](guide:{other['id']}).\n", actor="dev")
        self.assertTrue(store.merged(self.repo)[0]["edited"])

    def test_a_link_to_a_section_of_this_very_page_is_accepted(self):
        """
        Ссылка на собственный раздел — обычный приём внутри длинной
        страницы, и разбор обязан видеть разделы САМОЙ правки, а не
        только поставочные.
        """
        store.save(self.repo, self.page_id, title="Т",
                   body=("## Раздел {#own}\n\nТекст.\n\n"
                         f"См. [выше](guide:{self.page_id}/own).\n"),
                   actor="dev")
        self.assertTrue(store.merged(self.repo)[0]["edited"])

    def test_nothing_is_stored_when_the_format_is_wrong(self):
        """
        Разбор ДО записи: сломанная страница не должна попасть в базу
        даже на миг — читатель, открывший её в этот момент, увидит
        поломку, а откатывать будет уже администратор.
        """
        self._refuses("| таблица |\n")
        self.assertEqual(store.overrides(self.repo), {})


class WhoMayEditTests(unittest.TestCase):

    def setUp(self):
        self.repo = _repo()

    def test_an_admin_may(self):
        self.assertTrue(store.may_edit(self.repo, "someone", "admin"))

    def test_a_teacher_may_not(self):
        """
        Отличается от прав на СОДЕРЖАНИЕ ЗАДАНИЙ, где преподаватель
        полноправен: предмет преподавателя — его собственный, а страница
        базы знаний одна на всю установку.
        """
        self.assertFalse(store.may_edit(self.repo, "teacher1", "teacher"))

    def test_a_student_may_not(self):
        self.assertFalse(store.may_edit(self.repo, "student1", "student"))

    def test_a_guest_may_not(self):
        self.assertFalse(store.may_edit(self.repo, None, None))

    def test_a_superuser_may_whatever_role_says(self):
        """
        Разработчик опознаётся по `is_superuser`, а не по роли: роль
        приходит из сессии и говорит, ЧТО человек сейчас делает, а право
        на всю установку — свойство учётной записи.
        """
        logins = [u.login for u in self.repo.list_users()
                  if self.repo.is_superuser(u.login)]
        if not logins:
            self.skipTest("в поставочной базе нет суперпользователя")
        self.assertTrue(store.may_edit(self.repo, logins[0], "student"))

    def test_require_editor_names_who_may(self):
        with self.assertRaises(store.GuideAccessError) as caught:
            store.require_editor(self.repo, "teacher1", "teacher")
        message = str(caught.exception)
        self.assertIn("администратор", message.lower())
        self.assertIn("разработчик", message.lower())


if __name__ == "__main__":
    unittest.main()
