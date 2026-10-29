"""config.py — مسارات وإعدادات تشغيلية فقط.

لا توجد هنا أي قيمة من قواعد التوطين (نسب، حدود سريان، أجور، تواريخ، غرامات).
كل القواعد في rules/saudization_rules.json وتُعدَّل من صفحة «إعدادات القواعد» في التطبيق.
"""
import os
import shutil
import sys
from pathlib import Path

APP_VERSION = "5.2.0"

if getattr(sys, "frozen", False):                      # نسخة تنفيذية (PyInstaller)
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    DATA_DIR = Path(sys.executable).resolve().parent     # القواعد القابلة للتعديل بجانب البرنامج
else:
    BASE_DIR = Path(__file__).resolve().parents[1]
    DATA_DIR = BASE_DIR

DATA_DIR = Path(os.environ.get("INVENU_DATA_DIR", DATA_DIR))
RULES_FILE = DATA_DIR / "rules" / "saudization_rules.json"
RULES_BACKUP_DIR = DATA_DIR / "rules" / "backups"
if not RULES_FILE.exists():                            # أول تشغيل: انسخ القواعد الافتراضية
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE_DIR / "rules" / "saudization_rules.json", RULES_FILE)

# للموقع الداخلي: اجعل القواعد للقراءة فقط من الواجهة (تُعدَّل من الملف أو من حساب مسؤول)
RULES_READONLY = os.environ.get("INVENU_RULES_READONLY", "0") == "1"

# أعمدة ملف التأمينات (GOSI)
GOSI_KEY_COLUMN = "اسم المشترك"          # يُستخدم لاكتشاف صف العناوين تلقائياً
GOSI_REQUIRED_COLS = ["اسم المشترك", "رقم الهوية", "الجنسية", "المهنة",
                      "الأجر الأساسي", "إجمالي الأجر", "الاجر الخاضع للاشتراك"]
GOSI_OPTIONAL_COLS = ["الجنس", "تاريخ الإلتحاق"]
COLUMN_ALIASES = {
    "الأجر الخاضع للاشتراك": "الاجر الخاضع للاشتراك",
    "الاجر الاساسي": "الأجر الأساسي",
    "اجمالي الأجر": "إجمالي الأجر",
    "اجمالي الاجر": "إجمالي الأجر",
    "رقم الهويه": "رقم الهوية",
}
SAUDI_KEYWORDS = ("السعودية", "سعودي", "سعودية", "saudi", "ksa")
HEADER_SEARCH_ROWS = 25
