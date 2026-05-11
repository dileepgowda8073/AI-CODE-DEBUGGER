import sys; sys.path.insert(0, '.')
from app import analyze_python_static, detect_common_patterns, generate_fixed_code

code = """# Logic error: wrong condition
age = 18

if age > 18:
    print("You are eligible to vote")
else:
    print("You are not eligible to vote")"""

issues = analyze_python_static(code) + detect_common_patterns(code, 'python')
print(f"Found {len(issues)} issue(s)")
for x in issues:
    print(f"  - Line {x['line']} [{x['severity'].upper()}] {x['message']}")

fixed = generate_fixed_code(code, 'python', issues)
print("\n=== FIXED CODE ===")
print(fixed)
