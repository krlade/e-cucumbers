#!/bin/bash
echo "==================================================="
echo "    E-Cucumbers - Automatyczny Instalator Systemu"
echo "==================================================="
echo ""

echo "[1/3] Tworzenie wirtualnego srodowiska (.venv)..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Wirtualne srodowisko utworzone pomyslnie."
else
    echo "Wirtualne srodowisko juz istnieje, pomijanie..."
fi
echo ""

echo "[2/3] Aktywacja srodowiska i instalacja zaleznosci..."
source .venv/bin/activate
python3 -m pip install --upgrade pip
pip install -r requirements.txt
echo ""

echo "[3/3] Inicjalizacja bazy danych i konta administratora..."
python3 manage.py setup_db
echo ""

echo "==================================================="
echo "  Setup zakonczony pomyslnie! Srodowisko gotowe."
echo "==================================================="
echo ""
read -p "Czy chcesz uruchomic .venv oraz serwer deweloperski? [Y/n] " -r prompt
if [[ ! $prompt =~ ^[Nn]$ ]]; then
    source .venv/bin/activate
    python3 manage.py runserver
fi
