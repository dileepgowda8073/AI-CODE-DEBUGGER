import sys; sys.path.insert(0, '.')
from app import analyze_python_static, detect_common_patterns, generate_fixed_code

# Test divide-by-zero fix indentation
print("=== Test: Divide by zero fixed code ===")
code1 = """def divide_numbers(a, b):
    result = a / b
    return result

print(divide_numbers(10, 0))"""
issues1 = analyze_python_static(code1) + detect_common_patterns(code1, 'python')
fixed1 = generate_fixed_code(code1, 'python', issues1)
print(fixed1)
print()

# Test return print() fix indentation
print("=== Test: return print() fixed code ===")
code2 = """def get_greeting(name):
    return print("Hello, " + name)

message = get_greeting("Alice")
print("Got:", message)"""
issues2 = analyze_python_static(code2) + detect_common_patterns(code2, 'python')
fixed2 = generate_fixed_code(code2, 'python', issues2)
print(fixed2)
print()

# Test boundary bug fix indentation
print("=== Test: Boundary bug fixed code ===")
code3 = """age = 18

if age > 18:
    print("You are eligible to vote")
else:
    print("You are not eligible to vote")"""
issues3 = analyze_python_static(code3) + detect_common_patterns(code3, 'python')
fixed3 = generate_fixed_code(code3, 'python', issues3)
print(fixed3)
