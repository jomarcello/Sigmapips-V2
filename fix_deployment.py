#!/usr/bin/env python3
"""
Script om de syntax error in main.py te repareren.
Dit script zoekt naar de lijn met de health_check functie en zorgt ervoor dat
er geen 'import logging' of andere ongewenste tekst achter de return statement staat.
"""
import re
import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_main_file(file_path):
    """
    Fix the main.py file to correct the syntax error
    where an import statement was appended to a return statement
    """
    logger.info(f"Looking for file: {file_path}")
    
    if not os.path.exists(file_path):
        logger.error(f"File does not exist: {file_path}")
        return False
    
    try:
        # Read the file content
        with open(file_path, 'r') as file:
            content = file.read()
        
        # Find the problematic pattern - any text after time.time()
        pattern = r'(return\s*{\s*"status"\s*:\s*"healthy"\s*,\s*"timestamp"\s*:\s*time\.time\(\s*\)\s*}).*?(\n|$)'
        match = re.search(pattern, content)
        
        if match:
            logger.info(f"Found problematic pattern: {match.group(0)}")
            
            # Replace with correct code - just the return statement followed by newline
            fixed_content = re.sub(pattern, r'\1\n', content)
            
            # Back up the original file
            backup_path = file_path + '.bak'
            with open(backup_path, 'w') as backup:
                backup.write(content)
            logger.info(f"Created backup at: {backup_path}")
            
            # Write the fixed content
            with open(file_path, 'w') as file:
                file.write(fixed_content)
            
            logger.info("Successfully fixed the file")
            return True
        else:
            logger.warning("No problematic pattern found in the file")
            return False
    
    except Exception as e:
        logger.error(f"Error fixing file: {str(e)}")
        return False

if __name__ == "__main__":
    # Default path is the deployed path
    file_path = "/app/trading_bot/main.py"
    
    # Allow overriding from command line
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    
    success = fix_main_file(file_path)
    
    if success:
        print(f"✅ Successfully fixed {file_path}")
        sys.exit(0)
    else:
        print(f"❌ Failed to fix {file_path}")
        sys.exit(1) 
