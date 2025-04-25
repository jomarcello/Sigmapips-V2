#!/bin/bash
# Script om alle dependencies te installeren, inclusief yfinance

echo "Installing SigmaPips dependencies..."

# Zorg ervoor dat pip up-to-date is
python -m pip install --upgrade pip

# Installeer yfinance expliciet eerst
echo "Installing yfinance explicitly..."
pip install yfinance==0.2.36

# Installeer alle dependencies uit requirements.txt
echo "Installing all requirements from requirements.txt..."
pip install -r requirements.txt

echo "Done installing dependencies!" 
