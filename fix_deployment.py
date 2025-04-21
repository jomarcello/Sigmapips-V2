#!/usr/bin/env python3
"""
Script to fix syntax errors in Python files.
This script fixes cases where import statements are incorrectly placed
after return statements, causing syntax errors.
"""
import re
import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_python_file(file_path):
    """
    Fix Python files to correct syntax errors where import statements
    are placed after return statements or other invalid locations
    """
    logger.info(f"Looking for file: {file_path}")
    
    if not os.path.exists(file_path):
        logger.error(f"File does not exist: {file_path}")
        return False
    
    try:
        # Read the file content
        with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
            content = file.read()
        
        # Backup the original file
        backup_path = file_path + '.bak'
        with open(backup_path, 'w', encoding='utf-8') as backup:
            backup.write(content)
        logger.info(f"Created backup at: {backup_path}")
        
        # Find problematic patterns - any text after return statements
        pattern1 = r'(return\s*(?:{[^}]*}|[\w\d\."\'\[\]]+)\s*)import\s+.*?($|\n)'
        pattern2 = r'(return\s*(?:{[^}]*}|[\w\d\."\'\[\]]+)\s*;?\s*)import\s+.*?($|\n)'
        
        # Check if either pattern exists
        match1 = re.search(pattern1, content)
        match2 = re.search(pattern2, content)
        
        if match1 or match2:
            logger.info(f"Found problematic import after return statement")
            
            # Fix both possible patterns
            fixed_content = re.sub(pattern1, r'\1\2', content)
            fixed_content = re.sub(pattern2, r'\1\2', fixed_content)
            
            # Write the fixed content
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(fixed_content)
            
            logger.info("Successfully fixed the file")
            return True
        
        # Handle the specific case from the error message
        specific_pattern = r'(return\s*{\s*"status"\s*:\s*"healthy"\s*,\s*"timestamp"\s*:\s*time\.time\(\s*\)\s*})import\s+.*?($|\n)'
        match_specific = re.search(specific_pattern, content)
        
        if match_specific:
            logger.info(f"Found specific problematic pattern with health check")
            
            # Replace with correct code
            fixed_content = re.sub(specific_pattern, r'\1\2', content)
            
            # Write the fixed content
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(fixed_content)
            
            logger.info("Successfully fixed the file with specific pattern")
            return True
            
        # As a last resort, scan the entire file for any return statement followed by import
        # and add a newline between them
        lines = content.split('\n')
        fixed_lines = []
        was_modified = False
        
        for i, line in enumerate(lines):
            if i > 0 and 'import' in line and 'return' in lines[i-1] and ';' not in lines[i-1]:
                # If the previous line had a return and this line has an import
                fixed_lines.append(lines[i-1])
                fixed_lines.append('')  # Add empty line
                was_modified = True
            else:
                fixed_lines.append(line)
        
        if was_modified:
            logger.info("Fixed import statements by adding newlines")
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write('\n'.join(fixed_lines))
            return True
        
        logger.warning("No problematic patterns found in the file")
        return False
    
    except Exception as e:
        logger.error(f"Error fixing file: {str(e)}")
        logger.exception(e)
        return False

if __name__ == "__main__":
    # Default path is the deployed path
    file_path = "/app/trading_bot/main.py"
    
    # Allow overriding from command line
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    
    success = fix_python_file(file_path)
    
    if success:
        print(f"✅ Successfully fixed {file_path}")
        sys.exit(0)
    else:
        # Even if we couldn't find a problem, we don't want to fail the container startup
        print(f"⚠️ No issues found to fix in {file_path}")
        sys.exit(0)  # Return success even if no changes were made #!/usr/bin/env python3
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
