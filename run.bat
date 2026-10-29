@echo off
rem INVENU — امتثال التوطين: تشغيل بنقرة مزدوجة على ويندوز (يعمل على جهازك فقط، بدون إنترنت بعد أول تشغيل)
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo.
  echo  Python 3.9+ is required. Download it from https://www.python.org/downloads/
  echo  and tick "Add Python to PATH" during installation, then run this file again.
  echo  يتطلب Python 3.9 أو أحدث. ثبّته ثم شغّل هذا الملف مرة أخرى.
  echo.
  pause
  exit /b 1
)
if not exist .venv\installed.ok (
  echo [1/2] First run: preparing local environment ^(one time, needs internet^)...
  if not exist .venv %PY% -m venv .venv || goto :fail
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip >nul
  pip install -r requirements.txt || goto :fail
  echo ok> .venv\installed.ok
) else (
  call .venv\Scripts\activate.bat
)
echo [2/2] Starting INVENU Saudization tool...
python run.py %*
pause
exit /b 0
:fail
echo.
echo  Setup failed. Check your internet connection and run this file again.
echo  تعذّر التجهيز. تحقق من الاتصال بالإنترنت وأعد تشغيل الملف.
pause
exit /b 1
