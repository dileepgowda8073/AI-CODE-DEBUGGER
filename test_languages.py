import sys; sys.path.insert(0, '.')
from app import detect_common_patterns

tests = {
    'javascript': 'var x = 5;\nif (x == 5) { console.log(x); }',
    'typescript': 'var x = 5;\nif (x == 5) { console.log(x); }',
    'java':       'String s = "hello";\nif (s == "hello") { System.out.println(s); }',
    'c':          'char buf[10];\ngets(buf);\nscanf("%s", buf);\nint *p = new int;',
    'cpp':        'int *p = new int;\nchar s[10]; scanf("%s", s);',
    'csharp':     'string s = null;\nif (s == null) {}\nint x = int.Parse("5");',
    'go':         'val, err := os.Open("file")\ngo doWork()',
    'rust':       'let x = some_result.unwrap();\nlet y = other.expect("msg");\nlet z = a.clone().clone();',
    'php':        '$q = mysql_query($sql);\necho $_GET["name"];\nif ($x == 1) {}',
    'ruby':       'rescue Exception\nputs "a", "b"',
    'swift':      'var x = 5\nlet y = optVal!',
    'kotlin':     'var x = 5\nval z = nullable!!',
    'sql':        'SELECT * FROM users;\nDELETE FROM users;\nSELECT id FROM users;',
    'python':     'while True:\n    pass',
}

print("Language Coverage Test:")
print("-" * 50)
all_pass = True
for lang, code in tests.items():
    issues = detect_common_patterns(code, lang)
    status = "PASS" if issues else "MISS"
    if not issues:
        all_pass = False
    print(f"  {status} {lang:12s}: {len(issues)} issue(s) - {issues[0]['message'][:50] if issues else 'none'}")

print("-" * 50)
print("All languages detected:" if all_pass else "Some languages still missing detection")
