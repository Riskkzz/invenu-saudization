"""
build_web.py — يبني نسخة المتصفح (صفحة ثابتة تعمل بالكامل داخل متصفح المستخدم)
================================================================================
    python packaging/build_web.py                 # الناتج: dist/web/
    python -m http.server -d dist/web 8000        # تجربة محلية: http://127.0.0.1:8000

الناتج مجلد ثابت يُرفع كما هو إلى أي استضافة (GitHub Pages، موقع INVENU، ...).
لا يحتاج خادماً ولا قاعدة بيانات: محرك Python نفسه (backend/) يعمل داخل المتصفح عبر Pyodide،
وكل الملفات تُخدَم من نفس الموقع، وسياسة CSP تمنع الصفحة من الاتصال بأي جهة خارجية
عدا مزوّدي الذكاء الاصطناعي في backend/ai_service.PROVIDERS (ميزة المستشار الذكي (AI)، نص القرار فقط).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYODIDE_VERSION = "0.27.7"
PYODIDE_URL = f"https://github.com/pyodide/pyodide/releases/download/{PYODIDE_VERSION}/pyodide-{PYODIDE_VERSION}.tar.bz2"
PYODIDE_SHA256 = "08dd7f4fc4710110ea0fe2a7daa95bdf76001e596545267bc16dd760436ea755"
PYODIDE_CORE = ["pyodide.js", "pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json", "package.json"]
PYODIDE_PACKAGES = ["numpy", "pandas"]               # تُضاف تبعياتها تلقائياً من pyodide-lock.json
# مكتبات Python خالصة غير موجودة في Pyodide: تُضمَّن من PyPI بإصدار وبصمة ثابتين
PURE_WHEELS = {
    "openpyxl": ("https://files.pythonhosted.org/packages/py2.py3/o/openpyxl/openpyxl-3.1.5-py2.py3-none-any.whl",
                 "5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2"),
    "et_xmlfile": ("https://files.pythonhosted.org/packages/py3/e/et_xmlfile/et_xmlfile-2.0.0-py3-none-any.whl",
                   "7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa"),
}
BACKEND_SKIP = {"api.py"}                            # طبقة HTTP (FastAPI) لا تلزم في المتصفح
sys.path.insert(0, str(ROOT))
from backend.ai_service import PROVIDER_ORIGINS  # noqa: E402 — الاستثناء الوحيد في connect-src (المستشار الذكي)


def fetch(url: str, sha256: str, cache: Path) -> bytes:
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / url.rsplit("/", 1)[1]
    if not f.exists():
        print(f"  تنزيل {url}")
        with urllib.request.urlopen(url) as r, open(f, "wb") as out:
            shutil.copyfileobj(r, out)
    data = f.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        f.unlink()
        sys.exit(f"بصمة غير مطابقة لـ {f.name}: {got}")
    return data


def pyodide_files(tar_bytes: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:bz2") as tar:
        lock = json.load(tar.extractfile("pyodide/pyodide-lock.json"))["packages"]
        need, todo = set(), list(PYODIDE_PACKAGES)
        while todo:
            k = todo.pop()
            if k not in need:
                need.add(k)
                todo += lock[k]["depends"]
        names = PYODIDE_CORE + [lock[k]["file_name"] for k in sorted(need)]
        print(f"  حزم Pyodide: {', '.join(sorted(need))}")
        return {n: tar.extractfile(f"pyodide/{n}").read() for n in names}


def app_zip(wheels: dict[str, bytes]) -> bytes:
    """backend/ + rules/ + جسر المتصفح + openpyxl — يُفك داخل المتصفح في /home/pyodide/app."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "backend").glob("*.py")):
            if f.name not in BACKEND_SKIP:
                z.write(f, f"backend/{f.name}")
        z.write(ROOT / "rules" / "saudization_rules.json", "rules/saudization_rules.json")
        z.write(ROOT / "web" / "invenu_web_bridge.py", "invenu_web_bridge.py")
        for data in wheels.values():
            with zipfile.ZipFile(io.BytesIO(data)) as w:
                for n in w.namelist():
                    if ".dist-info/" not in n:
                        z.writestr(n, w.read(n))
    return buf.getvalue()


def csp_for(html: str) -> str:
    """CSP صارمة: لا اتصال إلا بنفس الموقع ومزوّدي الذكاء الاصطناعي المحددين. السكربتات المضمنة مسموحة ببصمتها فقط."""
    hashes = [base64.b64encode(hashlib.sha256(m.encode()).digest()).decode()
              for m in re.findall(r"<script>(.*?)</script>", html, re.S)]
    script = " ".join(["'self'", "'wasm-unsafe-eval'", "'unsafe-eval'", *[f"'sha256-{h}'" for h in hashes]])
    return ("default-src 'self'; "
            f"script-src {script}; "
            f"connect-src 'self' {' '.join(PROVIDER_ORIGINS)}; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'none'")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "dist" / "web"))
    ap.add_argument("--cache", default=str(ROOT / ".cache" / "web-build"))
    a = ap.parse_args()
    out, cache = Path(a.out), Path(a.cache)

    print("1) Pyodide")
    py = pyodide_files(fetch(PYODIDE_URL, PYODIDE_SHA256, cache))
    print("2) openpyxl")
    wheels = {k: fetch(u, h, cache) for k, (u, h) in PURE_WHEELS.items()}

    print(f"3) الإخراج: {out}")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "frontend", out)
    (out / "pyodide").mkdir()
    for n, data in py.items():
        (out / "pyodide" / n).write_bytes(data)
    (out / "py").mkdir()
    (out / "py" / "app.zip").write_bytes(app_zip(wheels))
    shutil.copy2(ROOT / "web" / "bridge.js", out / "js" / "bridge.js")
    (out / ".nojekyll").write_text("")                  # GitHub Pages: اخدم الملفات كما هي

    html = (out / "index.html").read_text(encoding="utf-8")
    html = html.replace('<html lang="ar" dir="rtl">', '<html lang="ar" dir="rtl" data-mode="web">', 1)
    html = html.replace('<script src="js/app.js"></script>',
                        '<script src="pyodide/pyodide.js"></script>\n<script src="js/bridge.js"></script>\n<script src="js/app.js"></script>', 1)
    html = html.replace('<meta charset="utf-8">',
                        f'<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="{csp_for(html)}">', 1)
    (out / "index.html").write_text(html, encoding="utf-8")

    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"تم. الحجم {size / 1e6:.1f} م.ب — جرّبه: python -m http.server -d {out} 8000")


if __name__ == "__main__":
    main()
