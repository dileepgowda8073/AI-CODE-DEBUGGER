import requests, json

code = """# Voting eligibility checker
age = 18

if age > 18:
    print("You are eligible to vote")
else:
    print("You are not eligible to vote")"""

r = requests.post('http://127.0.0.1:5000/api/analyze', json={'code': code, 'language': 'python'})
d = r.json()
print("=== CORRECTED CODE (repr) ===")
print(repr(d['result']['corrected_code']))
print()
print("=== CORRECTED CODE (display) ===")
print(d['result']['corrected_code'])
