#!/usr/bin/env python3
import re

# Open the file and read its contents
with open('trading_bot/services/calendar_service/tradingview_calendar.py', 'r') as f:
    content = f.read()

# Find the problematic section and fix its indentation
content = re.sub(
    r'                    \n                if not isinstance\(data, list\):', 
    r'                    \n                if not isinstance(data, list):', 
    content
)

# Fix all the indentation in this section
lines = content.split('\n')
indented_section = False
for i in range(len(lines)):
    if 'if not isinstance(data, list):' in lines[i]:
        indented_section = True
    elif indented_section and '                    logger.info(f"Received {len(data)} items from API")' in lines[i]:
        indented_section = False
    
    if indented_section and lines[i].startswith('                        '):
        lines[i] = lines[i].replace('                        ', '                    ', 1)

# Write the fixed content back to the file
with open('trading_bot/services/calendar_service/tradingview_calendar.py', 'w') as f:
    f.write('\n'.join(lines))

print("Fixed indentation issues in tradingview_calendar.py")
