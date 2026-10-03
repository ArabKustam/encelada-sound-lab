@echo off
rem Encelada Sound Lab: http://127.0.0.1:4790
rem Первый запуск создаёт .venv (Python 3.10+), ставит зависимости и скачивает живые инструменты (~1.6 ГБ).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Создаю .venv и ставлю зависимости...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -r soundlab\requirements.txt
  ".venv\Scripts\python.exe" -m pip install -q --no-deps tinysoundfont
)
if not exist "soundlab\instruments\salamander" ".venv\Scripts\python.exe" -m soundlab.install
start "" http://127.0.0.1:4790
".venv\Scripts\python.exe" -m soundlab.server
