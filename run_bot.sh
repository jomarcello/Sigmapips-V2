#!/bin/bash
echo "Starting SigmaPips Trading Bot..."

# Install any missing packages
echo "Installing dependencies..."
pip install --no-cache-dir twelvedata>=1.2.10

# Make sure we're in the right directory
cd "$(dirname "$0")"

echo "Starting the bot..."
python start_clean.py 
