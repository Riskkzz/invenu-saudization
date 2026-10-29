"""
rules_store.py — محرك القواعد الديناميكي (Dynamic Rules Engine)
================================================================
كل قواعد التوطين تُقرأ من ملف JSON واحد (rules/saudization_rules.json):

    groups[]       : المجموعات المهنية — النسبة ومراحلها، حد السريان، الحد الأدنى للأجر،
                     نطاق الاحتساب (group | subgroup | restricted)، والرابط الرسمي source_url
    professions[]  : خريطة المهن (Profession Mapping) — كل مسمى ورمزه ومجموعته
                     وتاريخ سريانه الخاص (إن وُجد) والمسميات البديلة aliases
    calculation    : طريقة التقريب، ووزن السعودي دون الحد الأدنى، وسياسة التداخل
    penalties      : الغرامات حسب فئة المنشأة
    establishment_categories : تعريف فئات المنشآت

لا تحتوي الدوال هنا على أي رقم من القواعد؛ كلها تُمرَّر من الملف.
"""
from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config as C
from .textutils import normalize_arabic

SCOPES = ("group", "subgroup", "restricted")


# ------------------------------------------------------------------
# قراءة وحفظ وتحقق
# ------------------------------------------------------------------
def load_rules(path: Path | str = C.RULES_FILE) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_rules(rules: dict, path: Path | str = C.RULES_FILE, backup: bool = True) -> Path:
    """يحفظ القواعد بعد التحقق، مع نسخة احتياطية مؤرخة من الملف السابق."""
    errors = validate_rules(rules)
    if errors:
        raise ValueError("لا يمكن الحفظ:\n- " + "\n- ".join(errors))
    path = Path(path)
    if backup and path.exists():
        C.RULES_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, C.RULES_BACKUP_DIR / f"rules_{datetime.now():%Y%m%d_%H%M%S}.json")
    rules = copy.deepcopy(rules)
    rules["version"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    path.write_text(json.dumps(rules, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def validate_rules(rules: dict) -> list[str]:
    errs: list[str] = []
    ids = [g.get("id") for g in rules.get("groups", [])]
    if len(ids) != len(set(ids)):
        errs.append("يوجد معرّف مجموعة مكرر")
    for g in rules.get("groups", []):
        gid = g.get("id", "?")
        if g.get("scope") not in SCOPES:
            errs.append(f"{gid}: نطاق الاحتساب يجب أن يكون أحد {SCOPES}")
        if not g.get("phases"):
            errs.append(f"{gid}: لا توجد مراحل (نسبة وتاريخ سريان)")
        for p in g.get("phases", []):
            r = p.get("ratio")
            if r is None or not (0 < float(r) <= 1):
                errs.append(f"{gid}: نسبة غير صالحة {r} (يجب أن تكون بين 0 و 1)")
            try:
                pd.Timestamp(p.get("effective_date"))
            except Exception:
                errs.append(f"{gid}: تاريخ سريان غير صالح {p.get('effective_date')}")
        if int(g.get("min_headcount", 0)) < 1:
            errs.append(f"{gid}: حد السريان يجب أن يكون 1 فأكثر")
        if int(g.get("min_establishment_size") or 0) < 0:
            errs.append(f"{gid}: حد حجم المنشأة لا يكون سالباً")
    known = set(ids)
    for p in rules.get("professions", []):
        if p.get("group") not in known:
            errs.append(f"المهنة «{p.get('title')}» مرتبطة بمجموعة غير موجودة: {p.get('group')}")
    return errs


# ------------------------------------------------------------------
# الوصول للقواعد
# ------------------------------------------------------------------
def groups_by_id(rules: dict) -> dict[str, dict]:
    return {g["id"]: g for g in rules["groups"]}


def build_title_index(rules: dict) -> dict[str, list[dict]]:
    """مسمى موحَّد ← قائمة المهن المطابقة (قد تكون أكثر من مجموعة عند التداخل)."""
    idx: dict[str, list[dict]] = {}
    enabled = {g["id"] for g in rules["groups"] if g.get("enabled", True)}
    for p in rules["professions"]:
        if p["group"] not in enabled:
            continue
        for t in [p["title"], *p.get("aliases", [])]:
            k = normalize_arabic(t)
            if k:
                idx.setdefault(k, []).append(p)
    return idx


def phase_at(group: dict, ref: pd.Timestamp, profession: dict | None = None) -> dict:
    """المرحلة السارية في تاريخ معيّن، والمرحلة التالية. تاريخ المهنة الخاص (إن وُجد) يؤخّر السريان."""
    phases = sorted(group["phases"], key=lambda p: p["effective_date"])
    floor = pd.Timestamp(profession["effective_date"]) if profession and profession.get("effective_date") else None
    cur, nxt = None, None
    for p in phases:
        d = pd.Timestamp(p["effective_date"])
        if floor is not None and d < floor:
            d = floor
        if d <= ref:
            cur = {"ratio": float(p["ratio"]), "date": d}
        elif nxt is None:
            nxt = {"ratio": float(p["ratio"]), "date": d}
    if cur is None:
        first = nxt
        return {"ratio": first["ratio"], "effective": first["date"], "enforced": False,
                "next_ratio": first["ratio"], "next_date": first["date"]}
    return {"ratio": cur["ratio"], "effective": cur["date"], "enforced": True,
            "next_ratio": nxt["ratio"] if nxt else float("nan"), "next_date": nxt["date"] if nxt else pd.NaT}


def min_wage(group: dict, wage_tier: str, subgroup: str | None = None) -> float:
    """الحد الأدنى للأجر من القواعد؛ NaN إن لم يُحدَّد. wage_tier = bachelor | diploma."""
    spec = None
    if subgroup and group.get("subgroups", {}).get(subgroup, {}).get("min_wage"):
        spec = group["subgroups"][subgroup]["min_wage"]
    spec = spec or group.get("min_wage")
    if not spec:
        return float("nan")
    if wage_tier in spec:
        return float(spec[wage_tier])
    if "default" in spec:
        return float(spec["default"])
    return float(max(spec.values()))


def round_required(x: float, mode: str) -> int:
    """التقريب حسب القواعد: half_up (الأدلة الإجرائية) | ceil | floor."""
    import math
    if mode == "ceil":
        return math.ceil(x - 1e-9)
    if mode == "floor":
        return math.floor(x + 1e-9)
    return math.floor(x + 0.5 + 1e-9)


def category_for(rules: dict, headcount: int) -> str:
    cats = sorted(rules["establishment_categories"], key=lambda c: -c["min_workers"])
    for c in cats:
        if headcount >= c["min_workers"]:
            return c["id"]
    return cats[-1]["id"]


# ------------------------------------------------------------------
# تحويل القواعد إلى جداول قابلة للتحرير في الواجهة والعكس
# ------------------------------------------------------------------
def to_frames(rules: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    g_rows, ph_rows = [], []
    for g in rules["groups"]:
        mw = g.get("min_wage") or {}
        g_rows.append({
            "id": g["id"], "الاسم": g["name"], "مفعّلة": g.get("enabled", True), "نطاق الاحتساب": g["scope"],
            "حد السريان": int(g["min_headcount"]),
            "أجر (افتراضي)": mw.get("default"), "أجر (بكالوريوس)": mw.get("bachelor"), "أجر (دبلوم)": mw.get("diploma"),
            "خاصة بنشاط": g.get("activity_specific", False), "الاعتماد المهني": g.get("accreditation", ""),
            "القرار": g.get("decision", ""), "موثّق": g.get("verified", False),
            "عنوان المصدر": g.get("source_title", ""), "source_url": g.get("source_url", ""), "ملاحظات": g.get("notes", ""),
        })
        for p in g["phases"]:
            ph_rows.append({"id": g["id"], "تاريخ السريان": pd.Timestamp(p["effective_date"]).date(), "النسبة %": round(float(p["ratio"]) * 100, 2)})
    pr_rows = [{"المسمى": p["title"], "الرمز": p.get("code", ""), "المجموعة": p["group"], "المجموعة الفرعية": p.get("subgroup") or "",
                "سريان خاص": pd.Timestamp(p["effective_date"]).date() if p.get("effective_date") else None,
                "مسميات بديلة": "، ".join(p.get("aliases", []))} for p in rules["professions"]]
    return pd.DataFrame(g_rows), pd.DataFrame(ph_rows), pd.DataFrame(pr_rows)


def from_frames(base: dict, gdf: pd.DataFrame, phdf: pd.DataFrame, prdf: pd.DataFrame) -> dict:
    """يعيد بناء القواعد من الجداول المحرَّرة مع الحفاظ على الحقول غير المعروضة (مثل subgroups)."""
    out = copy.deepcopy(base)
    old = groups_by_id(base)
    groups = []
    for _, r in gdf.dropna(subset=["id"]).iterrows():
        gid = str(r["id"]).strip()
        if not gid:
            continue
        g = copy.deepcopy(old.get(gid, {}))
        mw = {k: float(r[c]) for k, c in (("default", "أجر (افتراضي)"), ("bachelor", "أجر (بكالوريوس)"), ("diploma", "أجر (دبلوم)"))
              if pd.notna(r.get(c)) and str(r.get(c)) != ""}
        g.update({"id": gid, "name": str(r["الاسم"]), "enabled": bool(r["مفعّلة"]), "scope": str(r["نطاق الاحتساب"]),
                  "min_headcount": int(r["حد السريان"]), "min_wage": mw or None, "activity_specific": bool(r["خاصة بنشاط"]),
                  "accreditation": str(r.get("الاعتماد المهني") or ""), "decision": str(r.get("القرار") or ""),
                  "verified": bool(r.get("موثّق", False)), "source_title": str(r.get("عنوان المصدر") or ""),
                  "source_url": str(r.get("source_url") or ""), "notes": str(r.get("ملاحظات") or "")})
        ph = phdf[phdf["id"] == gid].dropna(subset=["تاريخ السريان", "النسبة %"])
        g["phases"] = [{"effective_date": str(pd.Timestamp(x["تاريخ السريان"]).date()), "ratio": float(x["النسبة %"]) / 100}
                       for _, x in ph.sort_values("تاريخ السريان").iterrows()]
        groups.append(g)
    out["groups"] = groups
    profs = []
    for _, r in prdf.dropna(subset=["المسمى", "المجموعة"]).iterrows():
        if not str(r["المسمى"]).strip():
            continue
        eff = r.get("سريان خاص")
        profs.append({"title": str(r["المسمى"]).strip(), "code": str(r.get("الرمز") or ""), "group": str(r["المجموعة"]).strip(),
                      "subgroup": (str(r.get("المجموعة الفرعية")).strip() or None) if pd.notna(r.get("المجموعة الفرعية")) else None,
                      "effective_date": str(pd.Timestamp(eff).date()) if pd.notna(eff) and str(eff) != "" else None,
                      "aliases": [a.strip() for a in str(r.get("مسميات بديلة") or "").replace(",", "،").split("،") if a.strip()]})
    out["professions"] = profs
    return out
