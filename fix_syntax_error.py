#!/usr/bin/env python3
"""
This script specifically targets the syntax error in /app/trading_bot/main.py
where 'import logging' is incorrectly added after the health_check return statement.
"""
import os
import re
import sys

def fix_health_check_syntax_error(file_path):
    """Fix the specific syntax error in the health_check function."""
    print(f"Checking file: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"Error: File does not exist: {file_path}")
        return False
    
    try:
        # Read the file
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # Back up the file before modifying
        backup_path = f"{file_path}.bak"
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Look for any variation of the health_check function with incorrect syntax
        pattern = r'(async\s+def\s+health_check\(\).*?return\s*{[^}]*"status"[^}]*"healthy"[^}]*time\.time\(\)[^}]*})([^\n]*?import.*?)(\n|$)'
        
        # Use re.DOTALL to match across multiple lines
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            # Replace with the correct version
            fixed_content = re.sub(pattern, r'\1\3', content, flags=re.DOTALL)
            
            # Write the fixed content back
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(fixed_content)
            
            print(f"✓ Fixed syntax error in health_check function in {file_path}")
            return True
        else:
            # Try direct replacement of the specific error reported in logs
            error_pattern = r'(return\s*{"status":\s*"healthy",\s*"timestamp":\s*time\.time\(\)})import\s+logging'
            if re.search(error_pattern, content):
                fixed_content = re.sub(error_pattern, r'\1', content)
                
                # Write the fixed content back
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(fixed_content)
                
                print(f"✓ Fixed specific import logging syntax error in {file_path}")
                return True
            
            # If we couldn't find the pattern, manually scan the file line by line
            lines = content.split('\n')
            fixed_lines = []
            made_change = False
            
            for i, line in enumerate(lines):
                if 'return {"status": "healthy", "timestamp": time.time()}' in line:
                    # Check if there's anything after the closing brace
                    match = re.search(r'(return\s*{"status":\s*"healthy",\s*"timestamp":\s*time\.time\(\)})(.+)', line)
                    if match:
                        # Found something after the return statement, remove it
                        fixed_lines.append(match.group(1))
                        made_change = True
                    else:
                        # No extra text, keep the line as is
                        fixed_lines.append(line)
                else:
                    fixed_lines.append(line)
            
            if made_change:
                # Write the fixed content back
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(fixed_lines))
                
                print(f"✓ Fixed syntax error by line-by-line scanning in {file_path}")
                return True
            
            print(f"ℹ No syntax error found in the health_check function in {file_path}")
            return False
            
    except Exception as e:
        print(f"Error fixing file: {str(e)}")
        return False

if __name__ == "__main__":
    # Default path for Docker deployment
    file_path = "/app/trading_bot/main.py"
    
    # Override with command line argument if provided
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    
    success = fix_health_check_syntax_error(file_path)
    sys.exit(0 if success else 1) 
