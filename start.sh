#!/bin/bash

# Set environment variables
export TELEGRAM_BOT_TOKEN="7328581013:AAFMGu8mz746nbj1eh6BuOp0erKl4Nb_-QQ"
export SUPABASE_URL="https://utigkgjcyqnrhpndzqhs.supabase.co"
export SUPABASE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InV0aWdrZ2pjeXFucmhwbmR6cWhzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MzYzMjMwNTYsImV4cCI6MjA1MTg5OTA1Nn0.QyCD9UnG80F8bTIK4dOMQagEo3iDgPiFm4azldv58Xo"
export DEEPSEEK_API_KEY="sk-274ea5952e7e4b87aba4b14de3990c7d"
export USE_MOCK_DATA="false"
export FORCE_POLLING="true"

# Run the bot
python3 main.py
