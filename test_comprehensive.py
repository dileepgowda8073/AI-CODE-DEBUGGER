import sys; sys.path.insert(0, '.')
from app import analyze_python_static, detect_common_patterns, generate_fixed_code

def test(name, code, expect_contains=""):
    issues = analyze_python_static(code) + detect_common_patterns(code, 'python')
    print(f"\n=== {name} ===")
    if issues:
        for iss in issues:
            print(f"  [{iss['severity'].upper()}] Line {iss.get('line','?')}: {iss['message']}")
        if expect_contains:
            found = any(expect_contains.lower() in iss['message'].lower() for iss in issues)
            print(f"  {'✅ PASS' if found else '❌ FAIL - expected: ' + expect_contains}")
    else:
        print("  No issues found")
        if expect_contains:
            print(f"  ❌ FAIL - expected: {expect_contains}")

# 1. Too few arguments
test("Too few args: add(1) but needs 2", """
def add(a, b):
    return a + b

result = add(1)
print(result)
""", "too few arguments")

# 2. Too many arguments
test("Too many args: add(1,2,3) but needs 2", """
def add(a, b):
    return a + b

result = add(1, 2, 3)
print(result)
""", "too many arguments")

# 3. Divide by zero literal
test("Divide by zero: a / 0", """
x = 10 / 0
""", "division by zero")

# 4. String + int type error
test("String + int: 'hello' + 5", """
msg = "Score: " + 5
print(msg)
""", "cannot concatenate")

# 5. Bare input() used arithmetically
test("Bare input() needs int()", """
num = input("Enter a number: ")
result = num + 10
print(result)
""", "input")

# 6. Infinite recursion
test("Infinite recursion: no base case", """
def countdown(n):
    return countdown(n - 1)

countdown(5)
""", "recursion")

# 7. Index out of range
test("Index out of range: [1,2,3][5]", """
items = [1, 2, 3]
print(items[5])
""", "")

# 8. Calling non-callable variable
test("Non-callable: result = 5; result()", """
result = 5
print(result())
""", "not callable")

# 9. Clean code - should find 0 issues
test("Clean code: no issues", """
def add(a, b):
    return a + b

print(add(2, 3))
""", "")

# 10. Show fixed code for too-few-args
print("\n=== Fixed code for add(1) with 2 params ===")
code = """def add(a, b):
    return a + b

result = add(1)
print(result)"""
issues = analyze_python_static(code) + detect_common_patterns(code, 'python')
print(generate_fixed_code(code, 'python', issues))
