"""
api.py — خادم محلي (FastAPI) يربط الواجهة بمحرك الامتثال
==========================================================
يعمل على 127.0.0.1 فقط. ملف التأمينات يُقرأ في الذاكرة ولا يُحفظ على القرص ولا يُرسل لأي جهة.
المنطق نفسه في service.py (تستخدمه نسخة المتصفح أيضاً)؛ هذا الملف طبقة HTTP فقط.

المسارات:
  GET  /                    الواجهة
  GET  /api/rules           القواعد الحالية
  PUT  /api/rules           حفظ القواعد بعد التحقق (مع نسخة احتياطية)
  POST /api/rules/reset     الرجوع لآخر نسخة محفوظة على القرص
  POST /api/rules/groups    اعتماد مسودة مجموعة (من المستشار الذكي) وإضافتها للقواعد
  POST /api/ai/extract      نص قرار + مفتاح API ← مسودة قاعدة للمراجعة (الاتصال الخارجي الوحيد: مزوّد الذكاء الاصطناعي)
  POST /api/upload          رفع ملف GOSI (.xlsx فقط) ← رمز جلسة
  POST /api/demo            بيانات مثال ← رمز جلسة
  POST /api/analyze         التحليل الكامل
  POST /api/simulate        محاكي «ماذا لو»
  POST /api/report          تقرير Excel
  GET  /api/health          فحص جاهزية الخادم (لـ Docker)
"""
from __future__ import annotations

from typing import List, Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config as C
from . import service as SV
from .service import ServiceError

FRONTEND = C.BASE_DIR / "frontend"

app = FastAPI(title="Saudization Compliance — INVENU", version=C.APP_VERSION, docs_url=None, redoc_url=None)


@app.exception_handler(ServiceError)
def _service_error(_: Request, exc: ServiceError):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


# Optional بدل «X | None»: نماذج pydantic تُقيَّم وقت التشغيل، وPython 3.9 (المدمج في ماك) لا يدعم «|».
class SettingsIn(BaseModel):
    reference_date: Optional[str] = None
    wage_tier: str = "bachelor"
    below_min_weight: Optional[float] = None
    include_activity_specific: bool = False
    category: Optional[str] = None
    repeat_multiplier: Optional[float] = None


class AnalyzeIn(BaseModel):
    token: str
    settings: SettingsIn = SettingsIn()
    lang: str = "ar"


class SimulateIn(AnalyzeIn):
    occupation: Optional[str] = None
    saudi: bool = True
    wage: float = 0
    count: int = 0
    remove_ids: List[str] = []


# ------------------------------------------------------------------
@app.get("/api/rules")
def get_rules():
    return SV.get_rules()


@app.put("/api/rules")
def put_rules(rules: dict):
    return SV.put_rules(rules)


@app.post("/api/rules/reset")
def reset_rules():
    return SV.reset_rules()


class AIExtractIn(BaseModel):
    text: str
    api_key: str = ""
    provider: Optional[str] = None
    model: Optional[str] = None


@app.post("/api/rules/groups")
def approve_group(draft: dict):
    return SV.approve_draft(draft)


@app.post("/api/ai/extract")
def ai_extract(body: AIExtractIn):
    return SV.ai_extract(body.text, body.api_key, body.provider, body.model)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    return SV.upload(await file.read(), file.filename)


@app.post("/api/demo")
def demo():
    return SV.demo()


@app.post("/api/analyze")
def analyze(body: AnalyzeIn):
    return SV.analyze(body.token, body.settings.model_dump())


@app.post("/api/simulate")
def simulate(body: SimulateIn):
    return SV.simulate(body.token, body.settings.model_dump(), body.occupation, body.saudi, body.wage, body.count, body.remove_ids)


@app.post("/api/report")
def report(body: AnalyzeIn):
    data, name = SV.report(body.token, body.settings.model_dump(), body.lang)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@app.get("/api/health")
def health():
    return {"status": "ok", "version": C.APP_VERSION}


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="static")
