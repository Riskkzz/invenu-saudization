# PyInstaller spec — يبني نسخة تنفيذية لا تحتاج Python على جهاز المستخدم.
#   pip install -r requirements-dev.txt
#   pyinstaller packaging/invenu_saudization.spec
# الناتج: dist/INVENU-Saudization/  (شغّل INVENU-Saudization.exe على ويندوز)
from pathlib import Path
root = Path(SPECPATH).parent
a = Analysis([str(root / "run.py")], pathex=[str(root)],
             datas=[(str(root / "frontend"), "frontend"), (str(root / "rules" / "saudization_rules.json"), "rules")],
             hiddenimports=["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.lifespan.on",
                            "openpyxl", "backend.api"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="INVENU-Saudization", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="INVENU-Saudization")
