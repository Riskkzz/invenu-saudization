"""reports.py — تقرير Excel ثنائي اللغة (العربية / English)."""
from __future__ import annotations

import io

import pandas as pd

from . import engine as E
from . import insights as I

STATUS = {"ar": {"risk": "مخالف الآن", "grace": "مخالف عند بدء الإلزام", "ok": "ممتثل", "na": "غير مشمول بالقرار"},
          "en": {"risk": "In violation now", "grace": "Violation once enforced", "ok": "Compliant", "na": "Not covered by the decision"}}
H = {
    "ar": {"groups": "الامتثال", "occ": "تفصيل المسميات", "emp": "الموظفون", "pen": "الغرامات", "gap": "تكلفة الفجوة", "recs": "التوصيات",
           "unit": "المجموعة المهنية", "threshold": "حد السريان", "n": "العاملون", "saudi": "سعوديون", "counted": "محتسبون",
           "ratio": "النسبة المطلوبة %", "cur": "النسبة الحالية %", "required": "المطلوب", "shortfall": "العجز", "headroom": "هامش الأمان",
           "status": "الحالة", "source": "الدليل الوزاري", "title": "المسمى الوظيفي", "name": "الاسم", "id": "رقم الهوية",
           "nat": "الجنسية", "occupation": "المهنة", "subject": "الأجر الخاضع للاشتراك", "total": "إجمالي الأجر", "minw": "الحد الأدنى",
           "is_counted": "يُحتسب"},
    "en": {"groups": "Compliance", "occ": "Job titles", "emp": "Employees", "pen": "Penalties", "gap": "Gap cost", "recs": "Recommendations",
           "unit": "Occupational group", "threshold": "Threshold", "n": "Workers", "saudi": "Saudis", "counted": "Counted",
           "ratio": "Required %", "cur": "Current %", "required": "Required", "shortfall": "Shortfall", "headroom": "Headroom",
           "status": "Status", "source": "Ministry guide", "title": "Job title", "name": "Name", "id": "ID", "nat": "Nationality",
           "occupation": "Occupation", "subject": "Insured wage", "total": "Total wage", "minw": "Minimum wage", "is_counted": "Counted"},
}


def excel_report(res: dict, lang: str = "ar") -> bytes:
    h, units, df = H[lang], res["units"], res["df"]
    uname = "unit" if lang == "ar" else "unit_en"
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame([{h["unit"]: u[uname], h["threshold"]: u["threshold"], h["n"]: u["n"], h["saudi"]: u["saudi"],
                       h["counted"]: u["counted"], h["cur"]: round(u["current_pct"] * 100, 1), h["ratio"]: round(u["ratio"] * 100, 1),
                       h["required"]: u["required"] if u["applicable"] else "", h["shortfall"]: u["shortfall"] if u["applicable"] else "",
                       h["headroom"]: u["headroom"] if u["applicable"] and u["compliant"] else "", h["status"]: STATUS[lang][u["status"]],
                       h["source"]: u["source_url"]} for _, u in units.iterrows()]).to_excel(xw, sheet_name=h["groups"], index=False)
        rows = []
        for _, u in units.iterrows():
            for _, o in E.occupation_breakdown(df, u["unit_id"]).iterrows():
                rows.append({h["unit"]: u[uname], h["title"]: o["المسمى الوظيفي"], h["n"]: o["العاملون"], h["saudi"]: o["سعوديون"],
                             h["counted"]: o["محتسبون"]})
        pd.DataFrame(rows).to_excel(xw, sheet_name=h["occ"], index=False)
        m = df[df["unit_id"].notna()]
        pd.DataFrame([{h["unit"]: e[uname], h["name"]: e["اسم المشترك"], h["id"]: e["رقم الهوية"], h["nat"]: e["الجنسية"],
                       h["occupation"]: e["المهنة"], h["subject"]: e["الاجر الخاضع للاشتراك"], h["total"]: e["إجمالي الأجر"],
                       h["minw"]: e["min_wage"], h["is_counted"]: bool(e["سعودي"] and e["أجر مطابق"])} for _, e in m.iterrows()]) \
            .to_excel(xw, sheet_name=h["emp"], index=False)
        res["penalties"].to_excel(xw, sheet_name=h["pen"], index=False)
        I.gap_cost(res).to_excel(xw, sheet_name=h["gap"], index=False)
        pd.DataFrame(res["recommendations"]).to_excel(xw, sheet_name=h["recs"], index=False)
        for ws in xw.book.worksheets:
            ws.sheet_view.rightToLeft = lang == "ar"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(12, *(len(str(c.value or "")) + 2 for c in col)))
    return buf.getvalue()
