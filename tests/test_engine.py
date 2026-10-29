"""اختبارات محرك الامتثال ببيانات افتراضية (لا تحتوي بيانات موظفين حقيقية)."""
import copy
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import data_loader as D  # noqa: E402
from backend import engine as E  # noqa: E402
from backend import rules_store as R  # noqa: E402

RULES = R.load_rules()
REF = pd.Timestamp("2026-10-23")


def staff(spec):
    """spec: [(المهنة, سعودي؟, الأجر, العدد)]"""
    rows, i = [], 0
    for occ, saudi, wage, n in spec:
        for _ in range(n):
            i += 1
            rows.append(D.make_employee_row(f"موظف {i}", "السعودية" if saudi else "وافد", occ, wage, str(1000 + i)))
    return pd.DataFrame(rows)


def unit(res, uid):
    return res["units"].set_index("unit_id").loc[uid]


def test_guide_example_marketing_16_workers_3_saudis():
    # مثال الدليل الإجرائي للتسويق: 60% × 16 − 3 = 6.6 ← 7
    g = staff([("أخصائي تسويق", True, 7000, 3), ("مصمم جرافيك", False, 7000, 13)])
    u = unit(E.run(g, RULES, E.Settings(REF)), "marketing")
    assert u["required"] == 10 and u["shortfall"] == 7 and u["status"] == "risk"


def test_group_level_not_per_title():
    # مصمم إعلان 1 سعودي من 4 (25%) لكن مجموعة التسويق ككل ممتثلة ← لا مخالفة
    g = staff([("مصمم إعلان", True, 7000, 1), ("مصمم إعلان", False, 7000, 3), ("أخصائي تسويق", True, 7000, 8)])
    res = E.run(g, RULES, E.Settings(REF))
    assert unit(res, "marketing")["status"] == "ok"
    assert not any("مصمم إعلان" in r["text"] for r in res["recommendations"])


def test_below_threshold_not_applicable():
    g = staff([("مندوب مبيعات", False, 6000, 2)])
    u = unit(E.run(g, RULES, E.Settings(REF)), "sales")
    assert not u["applicable"] and u["status"] == "na"


def test_saudi_below_min_wage_not_counted():
    g = staff([("أخصائي تسويق", True, 5000, 3), ("أخصائي تسويق", False, 7000, 2)])
    u = unit(E.run(g, RULES, E.Settings(REF)), "marketing")
    assert u["counted"] == 0 and u["under_wage"] == 3 and u["fixed_shortfall"] == 0


def test_restricted_profession_violation_and_overlap():
    g = staff([("أخصائي علاقات عامة", False, 9000, 1), ("أخصائي تسويق", True, 7000, 3)])
    res = E.run(g, RULES, E.Settings(REF))
    assert unit(res, "admin_support")["shortfall"] == 1          # بعد 04/10/2026 مقصورة
    assert unit(res, "marketing")["n"] == 3                       # خرجت من حسبة التسويق (النسبة الأعلى)
    before = E.run(g, RULES, E.Settings(pd.Timestamp("2026-09-01")))
    assert unit(before, "marketing")["n"] == 4                    # قبل التاريخ كانت ضمن التسويق
    assert unit(before, "admin_support")["upcoming_violations"] == 1 if "admin_support" in before["units"]["unit_id"].values else True


def test_rules_are_not_hardcoded():
    g = staff([("أخصائي تسويق", True, 7000, 5), ("أخصائي تسويق", False, 7000, 5)])
    r2 = copy.deepcopy(RULES)
    next(x for x in r2["groups"] if x["id"] == "marketing")["phases"] = [{"effective_date": "2026-01-01", "ratio": 0.4}]
    assert unit(E.run(g, RULES, E.Settings(REF)), "marketing")["status"] == "risk"   # 50% < 60%
    assert unit(E.run(g, r2, E.Settings(REF)), "marketing")["status"] == "ok"        # 50% ≥ 40%


def test_frames_roundtrip():
    gdf, ph, pr = R.to_frames(RULES)
    back = R.from_frames(RULES, gdf, ph, pr)
    assert R.validate_rules(back) == []
    assert len(back["professions"]) == len(RULES["professions"])
    assert [g["phases"] for g in back["groups"]] == [[{"effective_date": p["effective_date"], "ratio": pytest.approx(p["ratio"])} for p in g["phases"]] for g in RULES["groups"]]


def test_accounting_phase_change():
    g = staff([("محاسب تكاليف", True, 7000, 2), ("محاسب تكاليف", False, 7000, 3)])
    u1 = unit(E.run(g, RULES, E.Settings(pd.Timestamp("2026-10-26"))), "accounting")
    u2 = unit(E.run(g, RULES, E.Settings(pd.Timestamp("2026-10-27"))), "accounting")
    assert u1["ratio"] == 0.4 and u1["status"] == "ok"            # 40% × 5 = 2
    assert u2["ratio"] == 0.5 and u2["shortfall"] == 1             # 50% × 5 = 2.5 ← 3


def test_establishment_size_threshold_ohs():
    # السلامة والصحة المهنية تسري على المنشآت ذات 50 عاملاً فأكثر
    ohs = [("محترف السلامة والصحة المهنية", False, 8000, 1)]
    small = E.run(staff(ohs + [("سائق", False, 4000, 9)]), RULES, E.Settings(REF))
    u = unit(small, "ohs")
    assert not u["applicable"] and u["status"] == "na" and u["establishment_total"] == 10
    assert u["at_threshold"] is None and small["penalties"].empty
    assert any("50 عاملاً فأكثر" in r["text"] for r in small["recommendations"])
    big = E.run(staff(ohs + [("سائق", False, 4000, 49)]), RULES, E.Settings(REF))
    u = unit(big, "ohs")
    assert u["applicable"] and u["status"] == "risk" and u["shortfall"] == 1   # 70% × 1 ← 1


def test_establishment_size_applies_to_restricted_groups():
    r2 = copy.deepcopy(RULES)
    next(x for x in r2["groups"] if x["id"] == "admin_support")["min_establishment_size"] = 20
    g = staff([("أخصائي علاقات عامة", False, 9000, 1)])
    u = unit(E.run(g, r2, E.Settings(REF)), "admin_support")
    assert u["status"] == "na" and u["shortfall"] == 0 and u["violator_ids"] == []
    assert unit(E.run(g, RULES, E.Settings(REF)), "admin_support")["shortfall"] == 1   # بدون الشرط: مخالفة
    bad = copy.deepcopy(RULES)
    bad["groups"][0]["min_establishment_size"] = -1
    assert any("حجم المنشأة" in e for e in R.validate_rules(bad))
