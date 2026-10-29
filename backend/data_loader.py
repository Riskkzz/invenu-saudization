"""
data_loader.py — قراءة ملف التأمينات (GOSI) وتنظيفه
====================================================
- يكتشف صف العناوين تلقائياً (الجدول يبدأ عادةً من الصف الرابع)
- يحذف الأعمدة الفارغة الناتجة عن الخلايا المدمجة والصفوف الفاصلة
- يوحّد رقم الهوية ويحوّل الأجور لأرقام ويحدد السعوديين
"""
from __future__ import annotations

from typing import IO, Union

import numpy as np
import pandas as pd

from . import config as C
from .textutils import clean_text, normalize_arabic, to_number

FileLike = Union[str, "os.PathLike", IO[bytes]]


def _find_header_row(raw: pd.DataFrame, key: str) -> int:
    for i in range(min(len(raw), C.HEADER_SEARCH_ROWS)):
        if any(clean_text(v) == key for v in raw.iloc[i].tolist()):
            return i
    raise ValueError(f"لم يُعثر على عمود «{key}». تأكد أنك رفعت ملف المشتركين النشطين من التأمينات.")


def is_saudi(nationality) -> bool:
    n = normalize_arabic(nationality)
    return bool(n) and any(normalize_arabic(k) in n for k in C.SAUDI_KEYWORDS)


def read_gosi_file(file: FileLike) -> pd.DataFrame:
    raw = pd.read_excel(file, header=None, dtype=object)
    h = _find_header_row(raw, C.GOSI_KEY_COLUMN)
    df = raw.iloc[h + 1:].copy()
    df.columns = [clean_text(c) for c in raw.iloc[h].tolist()]
    df = df.loc[:, [isinstance(c, str) for c in df.columns]]
    df = df.rename(columns={k: v for k, v in C.COLUMN_ALIASES.items()})
    df = df.loc[:, ~df.columns.duplicated()]
    missing = [c for c in C.GOSI_REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError("الأعمدة التالية غير موجودة في ملف التأمينات: " + "، ".join(missing))
    df = df[C.GOSI_REQUIRED_COLS + [c for c in C.GOSI_OPTIONAL_COLS if c in df.columns]].copy()

    for col in ("اسم المشترك", "الجنسية", "المهنة", "الجنس"):
        if col in df.columns:
            df[col] = df[col].map(clean_text)
    df["رقم الهوية"] = df["رقم الهوية"].map(to_number)
    df = df[df["اسم المشترك"].notna() & df["رقم الهوية"].notna()].copy()
    df["رقم الهوية"] = df["رقم الهوية"].astype("int64").astype(str)
    for col in ("الأجر الأساسي", "إجمالي الأجر", "الاجر الخاضع للاشتراك"):
        df[col] = df[col].map(to_number).fillna(0.0).astype(float)
    if "تاريخ الإلتحاق" in df.columns:
        df["تاريخ الإلتحاق"] = pd.to_datetime(df["تاريخ الإلتحاق"], errors="coerce")
    df["المهنة"] = df["المهنة"].fillna("غير محدد")
    df["الجنسية"] = df["الجنسية"].fillna("غير محدد")
    df = df.drop_duplicates(subset="رقم الهوية").reset_index(drop=True)
    df["سعودي"] = df["الجنسية"].map(is_saudi)
    df["_key"] = df["المهنة"].map(normalize_arabic)
    return df


def make_employee_row(name: str, nationality: str, occupation: str, wage: float, emp_id: str = "SIM") -> dict:
    """صف موظف افتراضي (يُستخدم في محاكي التوظيف)."""
    return {"اسم المشترك": name, "رقم الهوية": emp_id, "الجنسية": nationality, "المهنة": occupation,
            "الأجر الأساسي": wage, "إجمالي الأجر": wage, "الاجر الخاضع للاشتراك": wage,
            "سعودي": is_saudi(nationality), "_key": normalize_arabic(occupation)}
