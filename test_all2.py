import sys
sys.path.insert(0, '.')
from app import analyze_python_static, detect_common_patterns, generate_fixed_code

tests = [
    ('Too few args: add(1)', 'def add(a, b):\n    return a + b\nresult = add(1)'),
    ('Too many args: add(1,2,3)', 'def add(a, b):\n    return a + b\nresult = add(1, 2, 3)'),
    ('Divide by zero literal', 'x = 10 / 0'),
    ('String + int concat', 'msg = "Score: " + 5\nprint(msg)'),
    ('Bare input() arithmetic', 'num = input("Enter: ")\nresult = num + 10\nprint(result)'),
    ('Infinite recursion', 'def countdown(n):\n    return countdown(n-1)\ncountdown(5)'),
    ('Non-callable variable', 'result = 5\nprint(result())'),
    ('CLEAN: correct add(2,3)', 'def add(a, b):\n    return a + b\nprint(add(2, 3))'),
]

for name, code in tests:
    issues = analyze_python_static(code) + detect_common_patterns(code, 'python')
    print(f'\n{name}: {len(issues)} issue(s)')
    for iss in issues:
        print(f'  [{iss["severity"].upper()}] L{iss.get("line","?")}: {iss["message"]}')
