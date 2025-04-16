import re

# Test patterns
tests = [
    'PPI (MoM) (Mar)',
    'GDP (YoY) (Q1)',
    'CPI (Apr)',
    'FOMC Member Barkin Speaks',
    'New Motor Vehicle Sales (MoM) (Feb)',
    'Employment Change (Q4)',
    'Inflation Rate (Jan/2024)'
]

for test in tests:
    # First remove quarter indicators (Q1), (Q2) etc.
    step1 = re.sub(r'\s*\(Q[1-4]\)\s*', ' ', test)
    # Remove month/year indicators like (Mar), (Apr), etc.
    step2 = re.sub(r'\s*\([A-Za-z]{3}\)\s*', ' ', step1)
    # Remove change period indicators like (MoM), (YoY), (QoQ)
    step3 = re.sub(r'\s*\((?:MoM|YoY|QoQ)\)\s*', ' ', step2)
    # Remove date patterns like (Jan/2024)
    step4 = re.sub(r'\s*\([A-Za-z]{3}/\d{4}\)\s*', ' ', step3)
    # Remove trailing spaces
    result = step4.strip()
    
    print(f"Original: '{test}'")
    print(f"Final result: '{result}'")
    print("-" * 50) 