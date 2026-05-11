import sys; sys.path.insert(0, '.')
from app import analyze_python_static, detect_common_patterns, generate_fixed_code

# Test 1: num = input() used in arithmetic → should get int() wrap
print("=== Test 1: bare input() used as number ===")
code1 = """num = input("Enter a number: ")
result = num + 10
print(result)"""
issues = analyze_python_static(code1) + detect_common_patterns(code1, 'python')
fixed = generate_fixed_code(code1, 'python', issues)
print(fixed)
print()

# Test 2: the "Python - Input Crash" example from chips
print("=== Test 2: Input Crash example ===")
code2 = """num1 = input("Enter first number: ")
num2 = input("Enter second number: ")
result = num1 / num2
print("Result:", result)"""
issues2 = analyze_python_static(code2) + detect_common_patterns(code2, 'python')
fixed2 = generate_fixed_code(code2, 'python', issues2)
print(fixed2)
print()

# Test 3: input() already wrapped with int() — should NOT double-wrap
print("=== Test 3: already int(input()) — no change ===")
code3 = """num = int(input("Enter a number: "))
print(num + 5)"""
issues3 = analyze_python_static(code3) + detect_common_patterns(code3, 'python')
fixed3 = generate_fixed_code(code3, 'python', issues3)
print(fixed3)
