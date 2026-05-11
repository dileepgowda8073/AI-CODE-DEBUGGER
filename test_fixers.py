import sys; sys.path.insert(0, '.')
from app import generate_fixed_code, analyze_python_static, detect_common_patterns

tests = [
    ('python - wrong args', 'python',
     'def add(a, b):\n    return a + b\nresult = add(1)\nprint(result)'),
    ('python - infinite loop', 'python',
     'while True:\n    x = 1'),
    ('python - input type error', 'python',
     'num = input("Enter: ")\nresult = num + 10\nprint(result)'),
    ('javascript - missing semi + ==', 'javascript',
     'let x = 5\nif (x == 5) {\n  console.log(x)\n}'),
    ('javascript - infinite loop', 'javascript',
     'while (true) {\n  doWork()\n}'),
    ('java - string ==', 'java',
     'String s = "hello";\nif (s == "hello") {\n  System.out.println(s);\n}'),
    ('java - missing semicolon', 'java',
     'int x = 5\nSystem.out.println(x)'),
    ('c - gets()', 'c',
     '#include <stdio.h>\nchar buf[10];\ngets(buf);'),
    ('csharp - int.Parse', 'csharp',
     'string s = "123";\nint x = int.Parse(s);'),
    ('rust - unwrap', 'rust',
     'let val = some_result.unwrap();\nprintln!("{}", val);'),
]

for name, lang, code in tests:
    if lang == 'python':
        issues = analyze_python_static(code) + detect_common_patterns(code, lang)
    else:
        issues = detect_common_patterns(code, lang)
    fixed = generate_fixed_code(code, lang, issues)
    print(f'\n=== {name} ({len(issues)} issues) ===')
    print(fixed[:400])
    print('---')
