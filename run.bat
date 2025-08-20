@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"

set "PYTHON_CMD=python"
where py >nul 2>nul
if %errorlevel%==0 (
	set "PYTHON_CMD=py -3"
)

if not exist "%VENV_DIR%" (
	%PYTHON_CMD% -m venv "%VENV_DIR%"
)

call "%VENV_DIR%\Scripts\activate.bat"

python -m pip install -r "%SCRIPT_DIR%requirements.txt"
python "%SCRIPT_DIR%app.py"

endlocal
