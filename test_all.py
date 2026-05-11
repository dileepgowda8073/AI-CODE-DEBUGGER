import sys; sys.path.insert(0, '.')
from app import analyze_python_static, detect_common_patterns

# Test 1: CORRECT code should have ZERO issues
print("=== Test 1: Clean code (should find 0 issues) ===")
code1 = """def greet(name):
    return "Hello, " + name

message = greet("Alice")
print(message)"""
issues1 = analyze_python_static(code1) + detect_common_patterns(code1, 'python')
print(f"Found {len(issues1)} issue(s)")
for x in issues1:
    print(f"  FALSE POSITIVE: Line {x['line']} [{x['severity']}] {x['message']}")

# Test 2: CORRECT division by len() should NOT be flagged
print("\n=== Test 2: Division by len() (should find 0 issues) ===")
code2 = """total = sum([1, 2, 3])
average = total / len([1, 2, 3])
print(average)"""
issues2 = analyze_python_static(code2) + detect_common_patterns(code2, 'python')
print(f"Found {len(issues2)} issue(s)")
for x in issues2:
    print(f"  FALSE POSITIVE: Line {x['line']} [{x['severity']}] {x['message']}")

# Test 3: Voting bug SHOULD be caught
print("\n=== Test 3: Voting boundary bug (should find 1 issue) ===")
code3 = """age = 18
if age > 18:
    print("eligible")
else:
    print("not eligible")"""
issues3 = analyze_python_static(code3) + detect_common_patterns(code3, 'python')
print(f"Found {len(issues3)} issue(s)")
for x in issues3:
    print(f"  GOOD: Line {x['line']} [{x['severity']}] {x['message']}")

# Test 4: Divide by zero SHOULD be caught  
print("\n=== Test 4: Divide by zero (should find issues) ===")
code4 = """def divide(a, b):
    result = a / b
    return result
print(divide(10, 0))"""
issues4 = analyze_python_static(code4) + detect_common_patterns(code4, 'python')
print(f"Found {len(issues4)} issue(s)")
for x in issues4:
    print(f"  GOOD: Line {x['line']} [{x['severity']}] {x['message']}")

# Test 5: return print() SHOULD be caught
print("\n=== Test 5: return print() bug (should find 1 issue) ===")
code5 = """def greet(name):
    return print("Hello " + name)"""
issues5 = analyze_python_static(code5) + detect_common_patterns(code5, 'python')
print(f"Found {len(issues5)} issue(s)")
for x in issues5:
    print(f"  GOOD: Line {x['line']} [{x['severity']}] {x['message']}")

# Test 6: Normal > comparison should NOT be flagged (no assignment nearby)
print("\n=== Test 6: Normal > comparison (should find 0 issues) ===")
code6 = """x = 10
if x > 5:
    print("big")"""
issues6 = analyze_python_static(code6) + detect_common_patterns(code6, 'python')
print(f"Found {len(issues6)} issue(s)")
for x in issues6:
    print(f"  FALSE POSITIVE: Line {x['line']} [{x['severity']}] {x['message']}")
