"""
run.py — تشغيل الأداة محلياً
=============================
    python run.py            يشغّل الخادم على http://127.0.0.1:8765 ويفتح المتصفح
    python run.py --port 9000 --no-browser

الخادم يستمع على 127.0.0.1 فقط: لا يمكن لأي جهاز آخر الوصول إليه، ولا تُرسل البيانات خارج الجهاز.
للنشر كموقع داخلي للشركة: استخدم --host 0.0.0.0 خلف خادم الشركة (انظر README).
"""
import argparse
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser(description="Saudization Compliance — INVENU")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    import uvicorn
    from backend.api import app
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '::') else a.host}:{a.port}"
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"\n  نظام امتثال التوطين يعمل على: {url}\n  Saudization compliance tool running at: {url}\n  (Ctrl+C للإيقاف / to stop)\n")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
