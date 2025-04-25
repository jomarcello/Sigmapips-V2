#!/bin/bash
# Start script voor SigmaPips Trading Bot

# Log header
echo "======================================================"
echo "          SIGMAPIPS TRADING BOT LAUNCHER              "
echo "======================================================"

# Controleer of Python is geïnstalleerd
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is niet geïnstalleerd. Installeer Python 3 en probeer het opnieuw."
    exit 1
fi

# Controleer Python versie (moet 3.8+ zijn)
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
if [ $(echo "$PYTHON_VERSION < 3.8" | bc) -eq 1 ]; then
    echo "ERROR: Python $PYTHON_VERSION gedetecteerd. SigmaPips vereist Python 3.8 of hoger."
    exit 1
fi

echo "Python $PYTHON_VERSION gedetecteerd. Dit is compatibel."

# Controleer of venv module beschikbaar is
if ! python3 -c "import venv" &> /dev/null; then
    echo "ERROR: Python venv module is niet beschikbaar. Installeer python3-venv en probeer het opnieuw."
    exit 1
fi

# Stel virtual environment in als die niet bestaat
if [ ! -d "venv" ]; then
    echo "Virtual environment niet gevonden. Nieuw environment maken..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "ERROR: Kon geen virtual environment maken. Controleer je Python installatie."
        exit 1
    fi
fi

# Activeer de virtual environment
echo "Virtual environment activeren..."
source venv/bin/activate

# Installeer dependencies als ze nog niet geïnstalleerd zijn
echo "Dependencies controleren..."
if ! pip show yfinance &> /dev/null; then
    echo "yfinance niet gevonden. Dependencies worden geïnstalleerd..."
    pip install --upgrade yfinance  # Install latest version
    pip install -r requirements.txt
else
    echo "Dependencies lijken al geïnstalleerd te zijn."
    # Update yfinance to latest version anyway
    pip install --upgrade yfinance
fi

# Controleer of .env bestand bestaat
if [ ! -f ".env" ]; then
    echo "LET OP: .env bestand niet gevonden. Sommige functionaliteiten kunnen beperkt zijn."
    echo "Het is aanbevolen om een .env bestand te maken met de benodigde API keys."
fi

# Start de bot
echo "======================================================"
echo "          SIGMAPIPS TRADING BOT STARTEN               "
echo "======================================================"
echo ""
python -m trading_bot.main

# Deactiveer de virtual environment wanneer de bot stopt
deactivate 
