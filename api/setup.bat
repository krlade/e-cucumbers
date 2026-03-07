@echo off
title E-Cucumbers Setup
echo ===================================================
echo     E-Cucumbers - Automatyczny Instalator Systemu
echo ===================================================
echo.

echo [1/3] Tworzenie wirtualnego srodowiska (.venv)...
if not exist ".venv" (
    python -m venv .venv
    echo Wirtualne srodowisko utworzone pomyslnie.
) else (
    echo Wirtualne srodowisko juz istnieje, pomijanie...
)
echo.

echo [2/3] Aktywacja srodowiska i instalacja zaleznosci...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.

echo [3/3] Inicjalizacja bazy danych i konta administratora...
python manage.py setup_db
echo.

echo ===================================================
echo   Setup zakonczony pomyslnie! Srodowisko gotowe.
echo ===================================================
echo.
set "run_server="
set /p run_server="Czy chcesz uruchomic .venv oraz serwer deweloperski? [Y/n] "
if /i "%run_server%"=="n" goto skip_run

call .venv\Scripts\activate.bat
python manage.py runserver

:skip_run
pause
