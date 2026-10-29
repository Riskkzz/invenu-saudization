"""textutils.py — تنظيف النصوص العربية والأرقام (بدون أي قواعد عمل)."""
from __future__ import annotations

import math
import re

import numpy as np

_DIACRITICS = re.compile(r"[ؗ-ًؚ-ْٰـ]")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")


def clean_text(value):
    """يزيل المسافات الزائدة والمحارف غير المرئية؛ يعيد NaN للقيم الفارغة."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return np.nan
    s = str(value).replace(" ", " ").replace("‏", "").replace("‎", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s if s and s.lower() not in {"nan", "none", "-", "—"} else np.nan


def normalize_arabic(value) -> str:
    """مفتاح مطابقة: يوحّد الهمزات والتاء المربوطة والألف المقصورة ويحذف التشكيل والرموز."""
    s = clean_text(value)
    if not isinstance(s, str):
        return ""
    s = _DIACRITICS.sub("", s)
    s = re.sub("[إأآٱ]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def to_number(value) -> float:
    """'6,000 ريال' أو '٥٠٠٠' ← رقم."""
    if value is None:
        return np.nan
    if isinstance(value, (int, float, np.number)):
        return float(value)
    m = re.search(r"\d[\d,]*\.?\d*", str(value).translate(_AR_DIGITS))
    return float(m.group(0).replace(",", "")) if m else np.nan
