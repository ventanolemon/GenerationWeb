"""
Снимки экрана для базы знаний — ГЕНЕРИРУЮТСЯ, а не снимаются руками.

    python -m scripts.guide_shots [--check]

Почему так. Снимок, снятый руками, устаревает молча: на картинке остаётся
кнопка, которой в продукте больше нет, и ни один тест этого не покажет.
Читатель при этом верит картинке больше, чем тексту, — она выглядит как
доказательство. Сгенерированный снимок пересобирается вместе с
интерфейсом, а `--check` говорит, что пора пересобрать.

Что здесь снимается и чем
-------------------------
Снимок делается из ЖИВОГО кода, а не из макета: страница собирается из
настоящих данных (задание — настоящей выдачей движка, разметка — теми же
классами, что в приложении) и рисуется headless-хромиумом. Поднимать при
этом весь стенд с сервером и сборкой не требуется: цена такой честности —
десятки секунд на снимок и зависимость от того, что в базе лежит сегодня.

Список снимков закрыт и лежит здесь же: каждая картинка в базе знаний
обязана быть в нём, иначе `core/test_guide.py` не даст на неё сослаться.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.guide import SHOTS_DIR, SHOTS_FILE          # noqa: E402

#: Где искать браузер. Путь из окружения — чтобы стенд не зависел от
#: конкретной установки; список — разумные умолчания.
_CHROME_CANDIDATES = [
    os.environ.get("GUIDE_CHROME", ""),
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    shutil.which("chromium") or "",
    shutil.which("chromium-browser") or "",
    shutil.which("google-chrome") or "",
]

_STYLE = """
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.5 -apple-system, "Segoe UI", system-ui,
         sans-serif; background: #0f172a; color: #e2e8f0; }
  .shell { padding: 0; }
  .topbar { display: flex; align-items: center; gap: 18px; padding: 12px 20px;
            border-bottom: 1px solid #24304a; background: #131f38; }
  .brand { font-weight: 700; letter-spacing: .2px; }
  .tab { opacity: .7; }
  .tab.active { opacity: 1; border-bottom: 2px solid #4f9dde; padding-bottom: 3px; }
  .body { display: grid; grid-template-columns: 230px 1fr; gap: 0; }
  .side { border-right: 1px solid #24304a; padding: 16px 18px; }
  .side h3 { margin: 0 0 10px; font-size: 12px; text-transform: uppercase;
             letter-spacing: .08em; opacity: .55; }
  .side div { padding: 5px 0; opacity: .85; }
  .side div.sel { color: #7cb8ec; font-weight: 600; }
  .main { padding: 22px 26px; }
  .card { background: #16233d; border: 1px solid #24304a; border-radius: 10px;
          padding: 18px 20px; max-width: 760px; }
  .statement { font-size: 15px; line-height: 1.6; white-space: pre-wrap; }
  .answer { margin-top: 18px; display: flex; gap: 10px; align-items: center; }
  .answer input { flex: 1; padding: 8px 11px; border-radius: 7px;
                  border: 1px solid #33456b; background: #101c33;
                  color: inherit; font: inherit; }
  .answer button { padding: 8px 16px; border-radius: 7px; border: 0;
                   background: #3f7fd0; color: #fff; font: inherit;
                   font-weight: 600; }
  .hint { margin-top: 12px; font-size: 12px; opacity: .6; }
  .katex { font-size: 1.05em; }
"""

#: KaTeX из зависимостей фронтенда. Формулы на снимке обязаны выглядеть
#: так же, как в продукте: снимок с сырым `\begin{pmatrix}` показывает
#: то, чего пользователь не видит НИКОГДА, — и это ровно та ложь, ради
#: ухода от которой снимки и генерируются. Поймано просмотром картинки.
_KATEX_DIR = _ROOT / "frontend" / "node_modules" / "katex" / "dist"


def _chrome() -> str:
    for candidate in _CHROME_CANDIDATES:
        if candidate and pathlib.Path(candidate).exists():
            return candidate
    raise SystemExit(
        "Не найден Chromium. Укажите путь в GUIDE_CHROME или установите "
        "chromium — снимки базы знаний делаются им.")


def _katex_head() -> str:
    """
    Подключение KaTeX локальными файлами, без сети.

    Отсутствие KaTeX — не повод не сделать снимок: лучше картинка с
    сырой формулой, чем никакой. Но молчать об этом нельзя, иначе
    подмена уедет в документацию незамеченной.
    """
    css = _KATEX_DIR / "katex.min.css"
    js = _KATEX_DIR / "katex.min.js"
    auto = _KATEX_DIR / "contrib" / "auto-render.min.js"
    if not (css.exists() and js.exists() and auto.exists()):
        print("ВНИМАНИЕ: KaTeX не найден — формулы попадут на снимок "
              "сырым латехом. Поставьте зависимости фронтенда.")
        return ""
    return (f'<link rel="stylesheet" href="file://{css}">'
            f'<script src="file://{js}"></script>'
            f'<script src="file://{auto}"></script>')


def _generator_page() -> str:
    """
    Разметка снимка «экран генератора» с НАСТОЯЩИМ заданием.

    Задание берётся выдачей движка, а не выдумывается: картинка в
    документации должна показывать то, что продукт действительно выдаёт.
    Если модель или разводка изменятся, изменится и снимок — в этом весь
    смысл генерации.
    """
    from core.graph.executor import GraphExecutor
    from core.graph.spec import GraphSpec
    from exercises.model_tasks import TASKS

    entry = TASKS["eigenvalues"]
    spec = dict(entry["graph"])
    spec["meta"] = dict(spec.get("meta", {}), seed=7)
    task = GraphExecutor(GraphSpec.parse(spec)).run()
    statement = "\n".join(b.render_plain() for b in task.statement).strip()

    subjects = ["Линейная алгебра", "Математический анализ", "Физика",
                "Английский язык", "ОПВС"]
    parts = ["Собственные значения матрицы", "Характеристический многочлен",
             "Треугольник: вершина по двум прямым", "Пирамида: плоскость грани"]
    side = "".join(f"<div>{s}</div>" for s in subjects)
    part_list = "".join(
        f'<div class="{"sel" if i == 0 else ""}">{p}</div>'
        for i, p in enumerate(parts))
    return f"""<!doctype html><meta charset="utf-8">
{_katex_head()}
<style>{_STYLE}</style>
<div class="shell">
  <div class="topbar">
    <span class="brand">Λ+ Лаборатория+</span>
    <span class="tab active">Генератор</span>
    <span class="tab">Аналитика</span>
    <span class="tab">Предметы</span>
    <span class="tab">Домашние задания</span>
  </div>
  <div class="body">
    <div class="side">
      <h3>Предмет</h3>{side}
      <h3 style="margin-top:18px">Раздел</h3>{part_list}
    </div>
    <div class="main">
      <div class="card">
        <div class="statement">{statement}</div>
        <div class="answer">
          <input placeholder="Ваш ответ" value="">
          <button>Проверить</button>
        </div>
        <div class="hint">Ответ проверяет сервер: у задания нет
          записанного текстом эталона — он вычисляется вместе с условием.</div>
      </div>
    </div>
  </div>
</div>
<script>
  if (window.renderMathInElement) {{
    renderMathInElement(document.body, {{
      delimiters: [{{left: "$", right: "$", display: false}}],
      throwOnError: false,
    }});
  }}
</script>"""


#: Закрытый список снимков: имя → (ширина, высота, сборщик разметки).
SHOTS = {
    "generator-main": (1120, 620, _generator_page),
}


def _render(name: str, width: int, height: int, html: str,
            out_dir: pathlib.Path) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.png"
    with tempfile.TemporaryDirectory() as tmp:
        page = pathlib.Path(tmp) / "page.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run(
            [_chrome(), "--headless", "--no-sandbox", "--disable-gpu",
             "--hide-scrollbars", "--allow-file-access-from-files",
             "--virtual-time-budget=3000",
             f"--window-size={width},{height}",
             f"--screenshot={target}", f"file://{page}"],
            check=True, capture_output=True, timeout=120)
    return target


def build(out_dir: pathlib.Path | None = None) -> list[str]:
    """Сделать все снимки и записать их список."""
    directory = out_dir or SHOTS_DIR
    made = []
    for name, (width, height, page) in sorted(SHOTS.items()):
        path = _render(name, width, height, page(), directory)
        made.append(name)
        print(f"{name}: {path.relative_to(_ROOT)} "
              f"({path.stat().st_size} байт)")
    SHOTS_FILE.write_text(
        json.dumps(sorted(made), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return made


def check() -> int:
    """
    Все ли снимки на месте. Код возврата годится как гейт.

    Устаревание СОДЕРЖИМОГО этим не ловится — для этого пришлось бы
    сравнивать картинки попиксельно и падать от любого сдвига шрифта.
    Ловится другое, и это важнее: снимок, на который ссылаются, но
    которого нет, и снимок, положенный руками мимо генератора.
    """
    listed = set(json.loads(SHOTS_FILE.read_text(encoding="utf-8"))) \
        if SHOTS_FILE.exists() else set()
    problems = []
    if listed != set(SHOTS):
        problems.append(
            f"список снимков разошёлся с генератором: в файле {sorted(listed)}, "
            f"в коде {sorted(SHOTS)}")
    for name in SHOTS:
        if not (SHOTS_DIR / f"{name}.png").exists():
            problems.append(f"нет файла снимка {name}.png")
    for path in SHOTS_DIR.glob("*.png") if SHOTS_DIR.exists() else []:
        if path.stem not in SHOTS:
            problems.append(
                f"{path.name}: снимок не значится у генератора — "
                f"положен руками?")
    for line in problems:
        print(line)
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="только проверить, не пересобирать")
    args = parser.parse_args()
    if args.check:
        return check()
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
