#!/bin/bash

echo "Fixing syntax error in bot.py..."

# Pad naar het bestand (relatief pad voor lokaal gebruik)
BOT_PY="./trading_bot/services/telegram_service/bot.py"

# Controleer of het bestand bestaat
if [ ! -f "$BOT_PY" ]; then
  echo "Bestand $BOT_PY niet gevonden!"
  exit 1
fi

# Zoek naar de zwevende docstring en verwijder deze
grep -n "Create and return a logger instance with the given name" "$BOT_PY" | while read -r line ; do
  line_num=$(echo "$line" | cut -d':' -f1)
  echo "Zwevende docstring gevonden op regel $line_num, wordt verwijderd..."
  sed -i '' "${line_num}d" "$BOT_PY"  # MacOS compatibele versie van sed
  echo "Docstring verwijderd."
done

echo "Reparatie voltooid. Probeer de bot nu opnieuw te starten." 