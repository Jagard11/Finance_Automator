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

rem Forward only --* flags to the app
set "FWD_ARGS="
for %%A in (%*) do (
    set "ARG=%%~A"
    call :checkflag
)
goto :run

:checkflag
if not defined ARG goto :eof
setlocal EnableDelayedExpansion
set "A=!ARG!"
if /i "!A:~0,2!"=="--" (
    if defined FWD_ARGS (
        endlocal & set "FWD_ARGS=%FWD_ARGS% !ARG!" & goto :eof
    ) else (
        endlocal & set "FWD_ARGS=!ARG!" & goto :eof
    )
)
endlocal
goto :eof

:run
python "%SCRIPT_DIR%app.py" %FWD_ARGS%

endlocal
