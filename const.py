"""
Константы и пути проекта. Все пути — относительно корня проекта,
без хардкода вроде C:\\Users\\... .
"""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = ROOT_DIR / "resources"
DB_PATH = RESOURCES_DIR / "users_database.db"
WORDS_DIR = RESOURCES_DIR / "words"
UI_FILES_DIR = RESOURCES_DIR / "ui_files"
