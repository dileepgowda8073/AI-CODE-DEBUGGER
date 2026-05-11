import os
import json
import re
import ast
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# Try to import the new google-genai SDK
try:
    from google import genai as google_genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        _client = google_genai.Client(api_key=GEMINI_API_KEY)
        AI_AVAILABLE = True
    else:
        _client = None
        AI_AVAILABLE = False
except ImportError:
    _client = None
    AI_AVAILABLE = False

# ─────────────────────────────────────────────
# Static analysis helpers
# ─────────────────────────────────────────────

def _is_zero(node):
    """Check if an AST node is a literal zero."""
    if isinstance(node, ast.Constant) and node.value == 0:
        return True
    # Python <3.8 uses ast.Num
    if hasattr(ast, 'Num') and isinstance(node, ast.Num) and node.n == 0:
        return True
    return False


def analyze_python_static(code: str):
    """Run AST-based static analysis on Python code."""
    issues = []
    try:
        tree = ast.parse(code)

        # ── Pre-build: map function names → their definitions ──
        fn_defs = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_defs[node.name] = node

        for node in ast.walk(tree):

            # ── 1. Direct divide-by-zero: a / 0, a // 0, a % 0 ──
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                if _is_zero(node.right):
                    op_sym = '/' if isinstance(node.op, ast.Div) else ('//' if isinstance(node.op, ast.FloorDiv) else '%')
                    lineno = getattr(node, 'lineno', 1)
                    issues.append({
                        "line": lineno, "type": "ZeroDivisionError", "severity": "error",
                        "message": f"Division by zero using `{op_sym} 0`",
                        "description": (
                            f"Line {lineno} divides by zero. Python raises `ZeroDivisionError` "
                            "immediately and your program crashes."
                        ),
                        "fix": "Add a check: `if b != 0: result = a / b` or use try/except ZeroDivisionError."
                    })

            # ── 2. Function called with 0 as a divisor argument ──
            if isinstance(node, ast.Call):
                fn_name = ""
                if isinstance(node.func, ast.Name):
                    fn_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fn_name = node.func.attr

                if fn_name and fn_name in fn_defs:
                    fn_node = fn_defs[fn_name]

                    # 2a. Wrong number of arguments
                    fn_args = fn_node.args
                    required = [a for a in fn_args.args]
                    n_defaults = len(fn_args.defaults)
                    n_required = len(required) - n_defaults
                    n_passed = len(node.args)
                    # Skip if *args or **kwargs present
                    has_vararg = fn_args.vararg is not None
                    has_kwarg  = fn_args.kwarg is not None
                    if not has_vararg and not has_kwarg:
                        lineno = getattr(node, 'lineno', 1)
                        if n_passed < n_required:
                            issues.append({
                                "line": lineno, "type": "TypeError", "severity": "error",
                                "message": f"`{fn_name}()` called with too few arguments ({n_passed} given, {n_required} required)",
                                "description": (
                                    f"`{fn_name}()` needs {n_required} argument(s) but you only passed {n_passed}. "
                                    f"Required: {', '.join(a.arg for a in required[:n_required])}. "
                                    "Python will raise `TypeError` when this line runs."
                                ),
                                "fix": f"Call with all required arguments: `{fn_name}({', '.join(a.arg for a in required)})`"
                            })
                        elif n_passed > len(required):
                            issues.append({
                                "line": lineno, "type": "TypeError", "severity": "error",
                                "message": f"`{fn_name}()` called with too many arguments ({n_passed} given, max {len(required)})",
                                "description": (
                                    f"`{fn_name}()` accepts at most {len(required)} argument(s) but you passed {n_passed}. "
                                    "Python will raise `TypeError` when this line runs."
                                ),
                                "fix": f"Remove the extra argument(s). `{fn_name}` only takes: {', '.join(a.arg for a in required)}"
                            })

                    # 2b. Argument is 0 and used as divisor inside function
                    for arg_idx, arg in enumerate(node.args):
                        if _is_zero(arg):
                            params = [a.arg for a in fn_node.args.args]
                            if arg_idx < len(params):
                                param_name = params[arg_idx]
                                for inner in ast.walk(fn_node):
                                    if isinstance(inner, ast.BinOp) and isinstance(inner.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                                        if isinstance(inner.right, ast.Name) and inner.right.id == param_name:
                                            lineno = getattr(node, 'lineno', 1)
                                            issues.append({
                                                "line": lineno, "type": "ZeroDivisionError", "severity": "error",
                                                "message": f"Calling `{fn_name}()` with 0 as divisor argument `{param_name}`",
                                                "description": (
                                                    f"You called `{fn_name}(...)` passing `0` for `{param_name}`. "
                                                    f"Inside `{fn_name}`, `{param_name}` is used as a divisor — this will crash."
                                                ),
                                                "fix": f"Pass a non-zero value, or guard inside `{fn_name}`: `if {param_name} == 0: return None`"
                                            })

            # ── 3. String + non-string type error: "hello" + 5 ──
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                left_str  = isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)
                right_str = isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)
                left_num  = isinstance(node.left, ast.Constant) and isinstance(node.left.value, (int, float))
                right_num = isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float))
                if (left_str and right_num) or (left_num and right_str):
                    lineno = getattr(node, 'lineno', 1)
                    issues.append({
                        "line": lineno, "type": "TypeError", "severity": "error",
                        "message": "Cannot concatenate string and number directly",
                        "description": (
                            f"Line {lineno} tries to combine a string and a number with `+`. "
                            "Python doesn't allow this — you must convert the number to a string first."
                        ),
                        "fix": "Wrap the number: `\"hello\" + str(5)` or use an f-string: `f\"hello {5}\"`"
                    })

            # ── 4. Index on an empty list literal: [][0] ──
            if isinstance(node, ast.Subscript):
                if isinstance(node.value, ast.List) and len(node.value.elts) == 0:
                    lineno = getattr(node, 'lineno', 1)
                    issues.append({
                        "line": lineno, "type": "IndexError", "severity": "error",
                        "message": "Indexing an empty list `[]`",
                        "description": "You are accessing an index of an empty list `[]`. This always causes `IndexError`.",
                        "fix": "Check `if len(my_list) > 0:` before indexing."
                    })

            # ── 5. Out-of-range literal index: [1,2,3][5] ──
            if isinstance(node, ast.Subscript):
                if isinstance(node.value, ast.List):
                    list_len = len(node.value.elts)
                    idx_node = node.slice
                    # Handle Python 3.8 Index wrapper
                    if hasattr(idx_node, 'value'):
                        idx_node = idx_node.value
                    if isinstance(idx_node, ast.Constant) and isinstance(idx_node.value, int):
                        idx_val = idx_node.value
                        # Negative index check
                        if idx_val >= list_len or idx_val < -list_len:
                            lineno = getattr(node, 'lineno', 1)
                            issues.append({
                                "line": lineno, "type": "IndexError", "severity": "error",
                                "message": f"List index {idx_val} is out of range (list has {list_len} elements)",
                                "description": (
                                    f"You are trying to access index `{idx_val}` of a list with only {list_len} element(s). "
                                    f"Valid indices are 0 to {list_len - 1} (or -{list_len} to -1 for negative). "
                                    "This causes `IndexError` at runtime."
                                ),
                                "fix": f"Use an index between 0 and {list_len - 1}."
                            })

            # ── 6. Bare `except:` without exception type ──
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                lineno = getattr(node, 'lineno', 1)
                issues.append({
                    "line": lineno, "type": "BestPractice", "severity": "warning",
                    "message": "Bare `except:` catches everything including system errors",
                    "description": "Using `except:` without specifying an exception type hides real bugs and catches keyboard interrupts.",
                    "fix": "Specify the exception: `except ValueError:` or `except ZeroDivisionError:` etc."
                })

            # ── 7. Infinite recursion: function calls itself with no base case ──
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                has_if  = any(isinstance(n, ast.If) for n in ast.walk(node))
                has_ret_const = any(
                    isinstance(n, ast.Return) and isinstance(getattr(n, 'value', None), ast.Constant)
                    for n in ast.walk(node)
                )
                calls_self = any(
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == node.name
                    for n in ast.walk(node)
                )
                if calls_self and not has_if and not has_ret_const:
                    lineno = getattr(node, 'lineno', 1)
                    issues.append({
                        "line": lineno, "type": "RecursionError", "severity": "error",
                        "message": f"`{node.name}()` calls itself with no base case — infinite recursion",
                        "description": (
                            f"`{node.name}` calls itself recursively but has no `if` condition to stop. "
                            "This will cause `RecursionError: maximum recursion depth exceeded`."
                        ),
                        "fix": "Add a base case: `if n <= 0: return value` before the recursive call."
                    })

            # ── 8. Calling a non-function (variable that's an int/str used as function) ──
            # e.g. result = 5; result()
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called_name = node.func.id
                # Find if this name was assigned a non-function literal earlier
                for assign_node in ast.walk(tree):
                    if isinstance(assign_node, ast.Assign):
                        for target in assign_node.targets:
                            if isinstance(target, ast.Name) and target.id == called_name:
                                val = assign_node.value
                                if isinstance(val, ast.Constant) and not callable(val.value):
                                    lineno = getattr(node, 'lineno', 1)
                                    issues.append({
                                        "line": lineno, "type": "TypeError", "severity": "error",
                                        "message": f"`{called_name}` is not callable — it's a {type(val.value).__name__}",
                                        "description": (
                                            f"You assigned `{called_name} = {repr(val.value)}` earlier, "
                                            f"but then tried to call it as `{called_name}()`. "
                                            f"A {type(val.value).__name__} is not a function and cannot be called."
                                        ),
                                        "fix": f"Remove the `()` after `{called_name}`, or define `{called_name}` as a function using `def {called_name}():`."
                                    })

    except SyntaxError as e:
        issues.append({
            "line": e.lineno or 1,
            "type": "SyntaxError",
            "severity": "error",
            "message": str(e.msg),
            "description": f"Python syntax error at line {e.lineno}: {e.msg}",
            "fix": "Check for missing colons, mismatched parentheses, or invalid syntax near this line."
        })

    # De-duplicate issues on the same line with the same message
    seen = set()
    unique = []
    for iss in issues:
        key = (iss.get('line'), iss.get('message'))
        if key not in seen:
            seen.add(key)
            unique.append(iss)
    return unique




def detect_common_patterns(code: str, language: str):
    """Heuristic pattern-based detection."""
    issues = []
    lines = code.split('\n')

    if language == 'python':
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            # 1. Infinite loop without break/return
            if stripped in ('while True:', 'while 1:'):
                block_lines = lines[i:]
                has_exit = any('break' in l or 'return' in l or 'sys.exit' in l
                                for l in block_lines[:20])
                if not has_exit:
                    issues.append({
                        "line": i, "type": "LogicWarning", "severity": "warning",
                        "message": "Possible infinite loop detected",
                        "description": "This `while True:` loop has no `break` or `return` in the next 20 lines. It may run forever and freeze your program.",
                        "fix": "Add a `break` or `return` inside the loop when a condition is met."
                    })

            # 2. Assignment = inside if (should be ==)
            if re.search(r'^if\s+\w+\s*=\s*[^=]', stripped):
                issues.append({
                    "line": i, "type": "LogicError", "severity": "error",
                    "message": "Assignment `=` used inside `if` condition",
                    "description": "You wrote `=` (which assigns a value) instead of `==` (which compares). Python will give a SyntaxError here.",
                    "fix": "Change `=` to `==`. Example: `if x == 5:` instead of `if x = 5:`."
                })

            # 3. Mutable default argument
            if re.search(r'def\s+\w+\(.*=\s*(\[\]|\{\})', stripped):
                issues.append({
                    "line": i, "type": "BestPractice", "severity": "warning",
                    "message": "Mutable default argument (list/dict)",
                    "description": "Using `[]` or `{}` as a default argument is a common Python trap. The same object is shared across all calls, causing unexpected behavior.",
                    "fix": "Use `None` as default: `def fn(x=None): x = x or []`"
                })

            # 4. Missing colon after if/for/while/def/class
            if re.match(r'^(if|elif|else|for|while|def|class|with|try|except|finally)\b', stripped):
                if not stripped.endswith(':') and not stripped.endswith('\\') and '#' not in stripped:
                    if not any(c in stripped for c in ['{', '}']):
                        issues.append({
                            "line": i, "type": "SyntaxError", "severity": "error",
                            "message": f"Missing colon `:` after `{stripped.split()[0]}` statement",
                            "description": f"In Python, `{stripped.split()[0]}` statements must end with a colon `:`. Without it, you get a SyntaxError.",
                            "fix": f"Add `:` at the end: `{stripped}:`"
                        })

            # 5. Off-by-one: age > 18 when age = 18 (boundary bug)
            m_obo = re.match(r'^if\s+(\w+)\s*>\s*(\d+)\s*:', stripped)
            if m_obo:
                var_name = m_obo.group(1)
                threshold = m_obo.group(2)
                # Only flag if the variable was ASSIGNED that exact value nearby
                for j in range(max(0, i-6), i-1):
                    prev = lines[j].strip()
                    if re.match(rf'^{var_name}\s*=\s*{threshold}\s*$', prev):
                        issues.append({
                            "line": i, "type": "LogicError", "severity": "warning",
                            "message": f"Boundary bug: `{var_name} > {threshold}` excludes {threshold} itself",
                            "description": (
                                f"You set `{var_name} = {threshold}` on line {j+1}, then check `if {var_name} > {threshold}:`. "
                                f"When {var_name} is exactly {threshold}, this condition is FALSE — the else branch runs instead. "
                                f"If {threshold} should be included, use `>=`."
                            ),
                            "fix": f"Change to `if {var_name} >= {threshold}:` to include the value {threshold}."
                        })
                        break

            # 6. Comparing with None/True/False using == instead of is
            if re.search(r'==\s*(True|False|None)\b', stripped) or re.search(r'\b(True|False|None)\s*==', stripped):
                issues.append({
                    "line": i, "type": "BestPractice", "severity": "info",
                    "message": "Use `is` instead of `==` for None/True/False",
                    "description": "Python style guide (PEP 8) says to use `is None` instead of `== None`. The `is` operator checks identity which is correct for singletons.",
                    "fix": "Replace `== None` with `is None`, `== True` with `is True`."
                })

            # 7. return print() — common beginner mistake
            if re.match(r'return\s+print\s*\(', stripped):
                issues.append({
                    "line": i, "type": "LogicError", "severity": "error",
                    "message": "`return print(...)` always returns None",
                    "description": "`print()` displays text but returns `None`. So `return print(x)` gives back `None`, not the value of `x`.",
                    "fix": "Print first, then return: `print(x)` on one line, `return x` on the next."
                })

            # 8. int(input()) without try/except
            if re.search(r'int\s*\(\s*input\s*\(', stripped) or re.search(r'float\s*\(\s*input\s*\(', stripped):
                nearby = '\n'.join(lines[max(0,i-3):i+3])
                if 'try' not in nearby and 'except' not in nearby:
                    issues.append({
                        "line": i, "type": "RuntimeWarning", "severity": "warning",
                        "message": "User input not validated — crash risk",
                        "description": "If the user types text instead of a number, `int(input())` crashes with ValueError. Always wrap user input conversion in try/except.",
                        "fix": "Use: `try:\\n    x = int(input())\\nexcept ValueError:\\n    print('Please enter a number')`"
                    })

            # 9. Unreachable code after return (same indent level)
            if re.match(r'return\b', stripped):
                curr_indent = len(line) - len(line.lstrip())
                for j in range(i, min(i + 3, len(lines))):
                    nxt = lines[j]
                    nxt_s = nxt.strip()
                    if not nxt_s or nxt_s.startswith('#'):
                        continue
                    nxt_indent = len(nxt) - len(nxt.lstrip())
                    if nxt_indent == curr_indent and nxt_s and not re.match(r'^(def|class|elif|else|except|finally)\b', nxt_s):
                        issues.append({
                            "line": j + 1, "type": "LogicError", "severity": "warning",
                            "message": "Unreachable code after `return`",
                            "description": f"Line {j+1} can never run because the function already returned on line {i}.",
                            "fix": "Remove this line, or move it before the `return`."
                        })
                        break

            # 10. Division by a variable without any zero-check in the function
            div_match = re.search(r'(\w+)\s*/\s*(\w+)', stripped)
            if div_match and not stripped.startswith('#') and not stripped.startswith('//'):
                divisor = div_match.group(2)
                # Only flag if divisor is a simple variable (not a function call like len())
                if divisor.isidentifier() and not re.search(rf'{divisor}\s*\(', stripped) and divisor not in ('True', 'False', 'None'):
                    nearby = '\n'.join(lines[max(0,i-8):i+3])
                    has_guard = re.search(rf'{divisor}\s*!=\s*0|{divisor}\s*>\s*0|{divisor}\s*==\s*0|ZeroDivisionError|try:', nearby)
                    if not has_guard:
                        issues.append({
                            "line": i, "type": "RuntimeWarning", "severity": "warning",
                            "message": f"Division by `{divisor}` without zero-check",
                            "description": f"If `{divisor}` is ever 0, this line crashes with `ZeroDivisionError`. There is no check to prevent this.",
                            "fix": f"Add a guard: `if {divisor} != 0:` before dividing, or use try/except."
                        })

        # Whole-code AST checks
        try:
            tree = ast.parse(code)

            # Track which variables are assigned from bare input()
            input_vars = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    val = node.value
                    # bare input() call — not wrapped in int() or float()
                    if (isinstance(val, ast.Call) and
                            isinstance(val.func, ast.Name) and
                            val.func.id == 'input'):
                        for t in node.targets:
                            if isinstance(t, ast.Name):
                                input_vars.add(t.id)

            # Check: input_var used in arithmetic → TypeError
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)):
                    lineno = getattr(node, 'lineno', 1)
                    left_inp  = isinstance(node.left, ast.Name) and node.left.id in input_vars
                    right_inp = isinstance(node.right, ast.Name) and node.right.id in input_vars
                    right_num = isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float))
                    left_num  = isinstance(node.left, ast.Constant) and isinstance(node.left.value, (int, float))
                    if (left_inp or right_inp):
                        var = node.left.id if left_inp else node.right.id
                        issues.append({
                            "line": lineno, "type": "TypeError", "severity": "error",
                            "message": f"`{var}` is from `input()` — it's a string, not a number",
                            "description": (
                                f"`input()` always returns a **string**. "
                                f"You are using `{var}` in arithmetic, but Python cannot do math on a string. "
                                "This will crash with `TypeError: can only concatenate str (not \"int\") to str`."
                            ),
                            "fix": f"Wrap the input with int(): `{var} = int(input(...))`  and add try/except ValueError to handle bad input."
                        })

            # Check: function missing return on all paths
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    has_return = any(isinstance(c, ast.Return) and c.value is not None for c in ast.walk(node))
                    if has_return:
                        last = node.body[-1] if node.body else None
                        if last and isinstance(last, ast.If):
                            if_ret = any(isinstance(s, ast.Return) for s in last.body)
                            else_ret = last.orelse and any(isinstance(s, ast.Return) for s in last.orelse)
                            if if_ret and not else_ret:
                                issues.append({
                                    "line": last.lineno, "type": "LogicError", "severity": "warning",
                                    "message": f"Function `{node.name}` missing return on else path",
                                    "description": f"`{node.name}` returns a value in the `if` branch but not in `else`. When the condition is false, it silently returns `None`.",
                                    "fix": "Add a `return` in the `else` branch or a default `return` at the end."
                                })
        except Exception:
            pass


    elif language in ('javascript', 'typescript'):
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('//'): continue

            # 1. == instead of ===
            if re.search(r'(?<![=!<>])==(?!=)', stripped) and '===' not in stripped:
                issues.append({"line": i, "type": "BestPractice", "severity": "warning",
                    "message": "Use `===` instead of `==` for strict equality",
                    "description": "`==` performs type coercion (e.g. `0 == false` is true). Use `===` to compare value AND type.",
                    "fix": "Replace `==` with `===` and `!=` with `!==`."})
            # 2. var keyword
            if re.search(r'\bvar\b', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "warning",
                    "message": "Avoid `var` — use `let` or `const`",
                    "description": "`var` is function-scoped and hoisted, causing hard-to-find bugs. Use `const` for constants, `let` for reassignable variables.",
                    "fix": "Replace `var` with `const` or `let`."})
            # 3. console.log left in production
            if re.search(r'\bconsole\.log\b', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "info",
                    "message": "`console.log` should be removed before production",
                    "description": "Leaving `console.log` in production code clutters the browser console and can expose sensitive data.",
                    "fix": "Remove `console.log` statements or use a proper logging library."})
            # 4. == null check (should use === null || === undefined)
            if re.search(r'==\s*null\b', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "info",
                    "message": "Use `=== null` or nullish check instead of `== null`",
                    "description": "`== null` matches both null and undefined due to coercion. Be explicit with `=== null` or use optional chaining `?.`.",
                    "fix": "Use `=== null` if you mean exactly null, or `value == null` intentionally for null/undefined both."})
            # 5. Async without await
            if re.search(r'\basync\s+function\b', stripped):
                fn_block = '\n'.join(lines[i:i+20])
                if 'await' not in fn_block:
                    issues.append({"line": i, "type": "LogicWarning", "severity": "warning",
                        "message": "`async` function has no `await` — may not behave as expected",
                        "description": "Declaring a function `async` but not using `await` inside means it returns a Promise that resolves immediately. You may be missing an `await`.",
                        "fix": "Add `await` before the async call inside the function, or remove `async` if not needed."})

    elif language in ('c', 'cpp', 'c++'):
        full_code = '\n'.join(lines)
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('//'): continue
            # 1. gets() — buffer overflow risk
            if 'gets(' in stripped:
                issues.append({"line": i, "type": "SecurityError", "severity": "error",
                    "message": "Unsafe `gets()` — buffer overflow risk",
                    "description": "`gets()` reads input with no size limit, causing buffer overflow vulnerabilities. It was removed in C11.",
                    "fix": "Use `fgets(buffer, sizeof(buffer), stdin)` instead."})
            # 2. scanf %s without width
            if re.search(r'scanf\s*\(\s*"[^"]*%s[^"]*"', stripped):
                issues.append({"line": i, "type": "SecurityError", "severity": "warning",
                    "message": "`scanf(\"%s\")` without size limit",
                    "description": "Reading a string with `%s` in scanf has no bounds — can overflow. Specify a width like `%255s`.",
                    "fix": "Use `scanf(\"%255s\", buffer)` or use `fgets()`."})
            # 3. new without delete
            if re.search(r'\bnew\b', stripped) and 'delete' not in full_code:
                issues.append({"line": i, "type": "MemoryLeak", "severity": "warning",
                    "message": "`new` without `delete` — memory leak",
                    "description": "Memory allocated with `new` must be freed with `delete`. Without it, your program leaks memory.",
                    "fix": "Add `delete ptr;` (or `delete[] arr;` for arrays) when done using the memory."})
            # 4. malloc without free
            if re.search(r'\bmalloc\s*\(', stripped) and 'free' not in full_code:
                issues.append({"line": i, "type": "MemoryLeak", "severity": "warning",
                    "message": "`malloc()` without `free()` — memory leak",
                    "description": "Every `malloc()` call must have a matching `free()` to release memory.",
                    "fix": "Call `free(ptr)` when the allocated memory is no longer needed."})
            # 5. Comparing char arrays with ==
            if re.search(r'\bchar\b.*==', stripped):
                issues.append({"line": i, "type": "LogicError", "severity": "error",
                    "message": "Use `strcmp()` to compare C strings, not `==`",
                    "description": "In C/C++, `==` on char arrays compares memory addresses, not string content. This always gives wrong results.",
                    "fix": "Use `strcmp(str1, str2) == 0` to compare strings."})

    elif language == 'java':
        full_code = '\n'.join(lines)
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('//'): continue
            # 1. String comparison with ==
            if re.search(r'==\s*"', stripped) or re.search(r'"\s*==', stripped):
                issues.append({"line": i, "type": "LogicError", "severity": "error",
                    "message": "String comparison with `==` — always use `.equals()`",
                    "description": "In Java, `==` checks if two references point to the same object, not if Strings have the same content. `str == \"hello\"` often returns false even when values match.",
                    "fix": "Use `str.equals(\"hello\")` or `\"hello\".equals(str)` to compare string content."})
            # 2. Catching generic Exception
            if re.search(r'catch\s*\(\s*Exception\b', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "warning",
                    "message": "Catching generic `Exception` is too broad",
                    "description": "Catching all `Exception`s hides real bugs. Catch only specific exceptions you expect.",
                    "fix": "Use specific exceptions: `catch (IOException e)` or `catch (NumberFormatException e)`."})
            # 3. System.out.println for debugging
            if re.search(r'System\.out\.print', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "info",
                    "message": "Use a logger instead of `System.out.println`",
                    "description": "`System.out.println` is fine for learning but not for real applications. Loggers give you control over log levels and output.",
                    "fix": "Use `java.util.logging.Logger` or `SLF4J` for proper logging."})
            # 4. NullPointerException risk
            if re.search(r'\w+\s*\.\s*\w+', stripped) and 'null' in full_code:
                if not re.search(r'if\s*\(\s*\w+\s*!=\s*null', '\n'.join(lines[max(0,i-5):i+2])):
                    if re.search(r'=\s*null', full_code):
                        pass  # Too noisy, skip
            # 5. Integer overflow (int for large values)
            if re.search(r'\bint\s+\w+\s*=\s*\d{10,}', stripped):
                issues.append({"line": i, "type": "LogicError", "severity": "error",
                    "message": "Integer overflow: value too large for `int`",
                    "description": "Java `int` holds values up to ~2.1 billion (2^31-1). Larger values overflow silently.",
                    "fix": "Use `long` instead of `int` for large numbers, e.g. `long x = 10000000000L;`"})

    elif language == 'csharp':
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('//'): continue
            # 1. == for string comparison (valid in C# but warn about null)
            if re.search(r'==\s*null', stripped) and re.search(r'string\b', '\n'.join(lines[:i])):
                issues.append({"line": i, "type": "BestPractice", "severity": "info",
                    "message": "Use `string.IsNullOrEmpty()` for null/empty string checks",
                    "description": "Checking `str == null` misses empty strings. Use `string.IsNullOrEmpty(str)` or `string.IsNullOrWhiteSpace(str)` for robustness.",
                    "fix": "Replace with `string.IsNullOrEmpty(str)` or `string.IsNullOrWhiteSpace(str)`."})
            # 2. catch (Exception) too broad
            if re.search(r'catch\s*\(\s*Exception\b', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "warning",
                    "message": "Catching generic `Exception` is too broad",
                    "description": "Catching all exceptions hides real problems. Catch specific exceptions you expect.",
                    "fix": "Use specific exceptions like `catch (IOException e)` or `catch (FormatException e)`."})
            # 3. Console.WriteLine left in code
            if re.search(r'Console\.WriteLine', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "info",
                    "message": "Consider using a logger instead of `Console.WriteLine`",
                    "description": "`Console.WriteLine` is fine for learning but production apps should use `ILogger` or NLog/Serilog.",
                    "fix": "Use a logging framework like `Microsoft.Extensions.Logging` for production code."})
            # 4. int.Parse without try/catch
            if re.search(r'\bint\.Parse\b', stripped):
                nearby = '\n'.join(lines[max(0,i-3):i+3])
                if 'try' not in nearby:
                    issues.append({"line": i, "type": "RuntimeError", "severity": "warning",
                        "message": "`int.Parse()` throws on invalid input — use `int.TryParse()`",
                        "description": "`int.Parse()` throws `FormatException` if the input is not a valid integer. `int.TryParse()` returns false instead.",
                        "fix": "Use: `if (int.TryParse(str, out int val)) { ... }` instead of `int.Parse(str)`."})

    elif language == 'go':
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('//'): continue
            # 1. Error not checked
            if re.search(r',\s*err\s*:?=', stripped):
                next_lines = '\n'.join(lines[i:i+3])
                if 'err' not in next_lines and 'if err' not in next_lines:
                    issues.append({"line": i, "type": "BestPractice", "severity": "warning",
                        "message": "Error return value not checked",
                        "description": "Go functions return errors as values. Ignoring `err` can lead to silent failures and unexpected behavior.",
                        "fix": "Add `if err != nil { log.Fatal(err) }` or handle the error appropriately."})
            # 2. _ used to discard error
            if re.search(r',\s*_\s*:?=', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "warning",
                    "message": "Error discarded with `_` — potential silent failure",
                    "description": "Using `_` to discard an error means failures are silently ignored. This can cause very hard-to-debug issues.",
                    "fix": "Handle the error: `val, err := fn(); if err != nil { return err }`"})
            # 3. Goroutine without sync
            if re.search(r'\bgo\s+\w+\(', stripped):
                full_code = '\n'.join(lines)
                if 'WaitGroup' not in full_code and 'sync' not in full_code and 'channel' not in full_code and '<-' not in full_code:
                    issues.append({"line": i, "type": "LogicWarning", "severity": "warning",
                        "message": "Goroutine launched without synchronization",
                        "description": "Starting a goroutine without `sync.WaitGroup` or channels means the main program may exit before the goroutine finishes.",
                        "fix": "Use `sync.WaitGroup` or a channel to wait for goroutines to complete."})

    elif language == 'rust':
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('//'): continue
            # 1. unwrap() without error handling
            if re.search(r'\.unwrap\(\)', stripped):
                issues.append({"line": i, "type": "RuntimeError", "severity": "warning",
                    "message": "`.unwrap()` panics if the value is `Err` or `None`",
                    "description": "Calling `.unwrap()` on a `Result` or `Option` that is `Err`/`None` causes a panic and crashes the program.",
                    "fix": "Use `match`, `if let`, or `.unwrap_or(default)` / `.expect(\"message\")` for better error handling."})
            # 2. expect() is slightly better but still panics
            if re.search(r'\.expect\(', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "info",
                    "message": "`.expect()` panics on failure — consider propagating error with `?`",
                    "description": "`.expect()` panics with your message on failure. For library code, propagate errors using the `?` operator instead.",
                    "fix": "In functions returning `Result`, use `?` to propagate: `let val = some_fn()?;`"})
            # 3. clone() overuse
            if stripped.count('.clone()') > 1:
                issues.append({"line": i, "type": "Performance", "severity": "info",
                    "message": "Multiple `.clone()` calls — consider using references instead",
                    "description": "Cloning creates a full copy of data, which is expensive. Use references (`&`) to borrow data instead of cloning.",
                    "fix": "Pass `&value` (reference) instead of `value.clone()` where ownership is not needed."})

    elif language == 'php':
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('//'): continue
            # 1. mysql_ functions (deprecated)
            if re.search(r'\bmysql_\w+\s*\(', stripped):
                issues.append({"line": i, "type": "SecurityError", "severity": "error",
                    "message": "`mysql_*` functions are deprecated and removed",
                    "description": "The old `mysql_*` functions were removed in PHP 7. They are also vulnerable to SQL injection.",
                    "fix": "Use `PDO` or `mysqli` with prepared statements instead."})
            # 2. SQL injection risk
            if re.search(r'\$_(GET|POST|REQUEST)\[', stripped) and re.search(r'(SELECT|INSERT|UPDATE|DELETE)', stripped, re.I):
                issues.append({"line": i, "type": "SecurityError", "severity": "error",
                    "message": "SQL Injection risk: user input in SQL query",
                    "description": "Putting `$_GET` or `$_POST` directly into SQL queries allows attackers to run arbitrary SQL commands.",
                    "fix": "Use PDO prepared statements: `$stmt = $pdo->prepare('SELECT * WHERE id = ?'); $stmt->execute([$id]);`"})
            # 3. == vs === in PHP
            if re.search(r'(?<![=!<>])==(?!=)', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "warning",
                    "message": "Use `===` instead of `==` in PHP",
                    "description": "PHP's `==` does type juggling: `0 == 'a'` is true, `0 == false` is true. Use `===` for strict comparison.",
                    "fix": "Replace `==` with `===` for strict type+value comparison."})
            # 4. echo with unescaped user input (XSS)
            if re.search(r'echo\s+\$_(GET|POST|REQUEST)', stripped):
                issues.append({"line": i, "type": "SecurityError", "severity": "error",
                    "message": "XSS risk: echoing unescaped user input",
                    "description": "Outputting `$_GET` or `$_POST` directly allows attackers to inject JavaScript (XSS attack).",
                    "fix": "Always escape output: `echo htmlspecialchars($_GET['input'], ENT_QUOTES, 'UTF-8');`"})

    elif language == 'ruby':
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('#'): continue
            # 1. puts vs print confusion
            if re.search(r'\bputs\b.*,', stripped):
                issues.append({"line": i, "type": "LogicWarning", "severity": "info",
                    "message": "`puts` prints each argument on a new line — use `print` to stay on same line",
                    "description": "`puts` adds a newline after each argument. If you're passing multiple args expecting them on one line, use `print` instead.",
                    "fix": "Use `print` for same-line output: `print 'hello', ' world'`"})
            # 2. rescue Exception (too broad)
            if re.search(r'rescue\s+Exception\b', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "warning",
                    "message": "`rescue Exception` catches system signals too — use `StandardError`",
                    "description": "`Exception` in Ruby is the base class for everything including `SignalException` and `Interrupt`. You'll catch Ctrl+C!",
                    "fix": "Use bare `rescue` or `rescue StandardError` to catch only normal errors."})
            # 3. == for symbol/string comparison
            if re.search(r'".*"\s*==\s*:|\s*:\w+\s*==\s*"', stripped):
                issues.append({"line": i, "type": "LogicError", "severity": "error",
                    "message": "String and Symbol are different types — `==` will always be false",
                    "description": "In Ruby, `\"hello\" == :hello` is always false. Strings and symbols are different types.",
                    "fix": "Convert: `str.to_sym == :hello` or `sym.to_s == \"hello\"`."})

    elif language == 'swift':
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('//'): continue
            # 1. Force unwrap !
            if re.search(r'\w+!(?!\s*=)', stripped) and '!=' not in stripped:
                issues.append({"line": i, "type": "RuntimeError", "severity": "warning",
                    "message": "Force unwrap `!` — crashes if value is nil",
                    "description": "Using `!` to force-unwrap an Optional crashes your app with a fatal error if the value is `nil`.",
                    "fix": "Use `if let value = optional { }` or `guard let value = optional else { return }` for safe unwrapping."})
            # 2. print() for debugging
            if re.search(r'\bprint\s*\(', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "info",
                    "message": "Use `os_log` or `Logger` instead of `print` in production",
                    "description": "`print()` is fine for debugging but doesn't appear in device logs in production. Use `os_log` for real logging.",
                    "fix": "Use `import os; os_log(\"message\")` for production logging."})
            # 3. var instead of let
            if re.search(r'^\s*var\s+\w+\s*=', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "info",
                    "message": "Use `let` instead of `var` if value won't change",
                    "description": "Swift prefers immutability. Using `var` for values that never change is an anti-pattern and disables compiler optimizations.",
                    "fix": "Replace `var` with `let` if the value is never reassigned."})

    elif language == 'kotlin':
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('//'): continue
            # 1. !! force non-null assertion
            if re.search(r'\w+!!', stripped):
                issues.append({"line": i, "type": "RuntimeError", "severity": "warning",
                    "message": "Non-null assertion `!!` — throws NullPointerException if null",
                    "description": "Using `!!` forces a nullable type to non-null. If the value is null, it throws `KotlinNullPointerException`.",
                    "fix": "Use safe call `?.` or Elvis operator `?: default` instead: `val x = nullable?.value ?: 0`"})
            # 2. var instead of val
            if re.search(r'^\s*var\s+\w+', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "info",
                    "message": "Prefer `val` (immutable) over `var` when value won't change",
                    "description": "Kotlin encourages immutability. Use `val` for read-only variables and `var` only when reassignment is needed.",
                    "fix": "Change `var` to `val` if the variable is only assigned once."})
            # 3. == for reference comparison (should use ===)
            if re.search(r'===', stripped):
                issues.append({"line": i, "type": "BestPractice", "severity": "info",
                    "message": "`===` checks reference equality in Kotlin",
                    "description": "In Kotlin, `==` calls `.equals()` (structural equality). `===` checks if both point to the same object (referential equality).",
                    "fix": "Use `==` for value comparison and `===` only when you specifically need reference equality."})

    elif language == 'sql':
        for i, line in enumerate(lines, 1):
            stripped = line.strip().upper()
            if stripped.startswith('--'): continue
            # 1. SELECT *
            if re.search(r'\bSELECT\s+\*\b', stripped):
                issues.append({"line": i, "type": "Performance", "severity": "warning",
                    "message": "`SELECT *` fetches all columns — specify only needed columns",
                    "description": "Using `SELECT *` fetches every column, even ones you don't need. This wastes bandwidth, memory, and prevents the DB from using index-only scans.",
                    "fix": "List only the columns you need: `SELECT id, name, email FROM users`"})
            # 2. DELETE/UPDATE without WHERE
            if re.search(r'\b(DELETE\s+FROM|UPDATE\s+\w+\s+SET)\b', stripped) and 'WHERE' not in stripped:
                issues.append({"line": i, "type": "DataLoss", "severity": "error",
                    "message": "DELETE/UPDATE without WHERE — affects ALL rows!",
                    "description": "A DELETE or UPDATE without a WHERE clause modifies every row in the table. This can wipe or corrupt all your data.",
                    "fix": "Always add a WHERE clause: `DELETE FROM users WHERE id = 5`"})
            # 3. No LIMIT on SELECT
            if re.search(r'\bSELECT\b', stripped) and 'LIMIT' not in stripped and 'TOP' not in stripped:
                issues.append({"line": i, "type": "Performance", "severity": "info",
                    "message": "Consider adding LIMIT to prevent fetching too many rows",
                    "description": "Without LIMIT, a SELECT can return millions of rows, overloading your app and database.",
                    "fix": "Add `LIMIT 100` at the end of your query, or use pagination."})

    return issues




def generate_fixed_code(code: str, language: str, issues: list) -> str:
    """
    Apply rule-based fixes to produce corrected code without AI.
    Returns the fixed code string.
    """
    lines = code.split('\n')
    fixed = lines[:]

    issue_types  = {iss.get('type','')    for iss in issues}
    issue_msgs   = ' '.join(iss.get('message','') for iss in issues)
    issue_lines  = {iss.get('line', 0)   for iss in issues}

    if language == 'python':
        # ── 1. Fix missing colons ──
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if re.match(r'^(if|elif|else|for|while|def|class|with|try|except|finally)\b', stripped):
                if stripped and not stripped.endswith(':') and not stripped.endswith('\\') and '#' not in stripped:
                    if not any(c in stripped for c in ['{', '}']):
                        indent = len(line) - len(line.lstrip())
                        fixed[i] = ' ' * indent + stripped + ':'

        # ── 2. Fix divide-by-zero in function body ──
        import ast as _ast
        try:
            tree = _ast.parse(code)
            for node in _ast.walk(tree):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    fn_start = node.lineno - 1
                    fn_end   = node.end_lineno
                    fn_lines = fixed[fn_start:fn_end]
                    has_div   = any(re.search(r'[a-zA-Z_]\w*\s*/\s*[a-zA-Z_]\w*', l) for l in fn_lines)
                    has_guard = any(re.search(r'!= 0|> 0|ZeroDivisionError|try:', l) for l in fn_lines)
                    if has_div and not has_guard:
                        for j, fl in enumerate(fn_lines):
                            if re.search(r'[a-zA-Z_]\w*\s*/\s*[a-zA-Z_]\w*', fl) and 'def ' not in fl:
                                indent = len(fl) - len(fl.lstrip())
                                spc = ' ' * indent
                                spc4 = ' ' * (indent + 4)
                                orig_stripped = fl.strip()
                                global_idx = fn_start + j
                                # Replace single line with 4 properly indented lines
                                replacement = [
                                    spc + 'try:',
                                    spc4 + orig_stripped,
                                    spc + 'except ZeroDivisionError:',
                                    spc4 + 'raise ValueError("Cannot divide by zero!")'
                                ]
                                fixed[global_idx:global_idx+1] = replacement
                                break
        except Exception:
            pass

        # ── 3. Fix mutable default arguments ──
        for i, line in enumerate(fixed):
            if re.search(r'def\s+\w+\([^)]*=\s*(\[\]|\{\})', line):
                fixed[i] = re.sub(r'=\s*\[\]', '=None', line)
                fixed[i] = re.sub(r'=\s*\{\}', '=None', fixed[i])

        # ── 4. Fix off-by-one: > to >= when variable was assigned the threshold ──
        for i, line in enumerate(fixed):
            stripped = line.strip()
            m_fix = re.match(r'^(if\s+)(\w+)(\s*)(>)(\s*)(\d+)(\s*:.*)$', stripped)
            if m_fix:
                var_name = m_fix.group(2)
                threshold = m_fix.group(6)
                for j in range(max(0, i-5), i):
                    prev = fixed[j].strip()
                    if re.match(rf'^{var_name}\s*=\s*{threshold}\s*$', prev):
                        indent = len(line) - len(line.lstrip())
                        fixed[i] = ' ' * indent + stripped.replace(f'{var_name} > {threshold}', f'{var_name} >= {threshold}', 1)
                        break

        # ── 5. Fix return print() ──
        for i, line in enumerate(fixed):
            stripped = line.strip()
            m_rp = re.match(r'return\s+print\s*\((.+)\)\s*$', stripped)
            if m_rp:
                inner = m_rp.group(1)
                indent = len(line) - len(line.lstrip())
                spc = ' ' * indent
                fixed[i:i+1] = [spc + f'print({inner})', spc + f'return {inner}']

        # ── 5b. Fix wrong argument count: add missing args / remove extras ──
        import ast as _ast2
        try:
            _tree2 = _ast2.parse(code)
            _fn_defs2 = {}
            for _n in _ast2.walk(_tree2):
                if isinstance(_n, (_ast2.FunctionDef, _ast2.AsyncFunctionDef)):
                    _fn_defs2[_n.name] = _n
            for _n in _ast2.walk(_tree2):
                if isinstance(_n, _ast2.Call):
                    _fname = ''
                    if isinstance(_n.func, _ast2.Name):
                        _fname = _n.func.id
                    if _fname and _fname in _fn_defs2:
                        _fnode = _fn_defs2[_fname]
                        _params = [a.arg for a in _fnode.args.args]
                        _n_req  = len(_params) - len(_fnode.args.defaults)
                        _n_pass = len(_n.args)
                        _lineno = getattr(_n, 'lineno', None)
                        if _lineno and (_n_pass < _n_req or _n_pass > len(_params)):
                            # Rewrite call line with correct number of args
                            idx = _lineno - 1
                            if 0 <= idx < len(fixed):
                                old_line = fixed[idx]
                                indent   = len(old_line) - len(old_line.lstrip())
                                spc      = ' ' * indent
                                if _n_pass < _n_req:
                                    # Add placeholder args for missing ones
                                    missing = _params[_n_pass:_n_req]
                                    orig_call = old_line.strip()
                                    # Insert '0' placeholders for missing args before closing paren
                                    placeholders = ', '.join('0' for _ in missing)
                                    fixed_call = re.sub(
                                        rf'{re.escape(_fname)}\(([^)]*)\)',
                                        lambda m: f'{_fname}({m.group(1) + (", " if m.group(1).strip() else "") + placeholders})',
                                        orig_call, count=1
                                    )
                                    fixed[idx] = spc + fixed_call
                                    # Add comment explaining the fix
                                    fixed.insert(idx, spc + f'# FIX: Added missing argument(s): {missing}')
                                else:
                                    # Too many args — just add a comment
                                    fixed.insert(idx, spc + f'# FIX: {_fname}() takes {len(_params)} arg(s), check extra arguments below')
        except Exception:
            pass

        # ── 5c. Fix non-callable: x = 5; x() → x = 5; x ──
        try:
            _tree3 = _ast2.parse(code)
            _assigned_vals = {}
            for _n in _ast2.walk(_tree3):
                if isinstance(_n, _ast2.Assign):
                    for _t in _n.targets:
                        if isinstance(_t, _ast2.Name):
                            if isinstance(_n.value, _ast2.Constant):
                                _assigned_vals[_t.id] = _n.value.value
            for _n in _ast2.walk(_tree3):
                if isinstance(_n, _ast2.Call) and isinstance(_n.func, _ast2.Name):
                    _cname = _n.func.id
                    if _cname in _assigned_vals:
                        _lineno = getattr(_n, 'lineno', None)
                        if _lineno:
                            idx = _lineno - 1
                            if 0 <= idx < len(fixed):
                                # Remove the () from the call
                                fixed[idx] = re.sub(rf'\b{re.escape(_cname)}\s*\(\)', _cname, fixed[idx])
                                fixed.insert(idx, ' ' * (len(fixed[idx]) - len(fixed[idx].lstrip())) + f'# FIX: `{_cname}` is a value, not a function — removed ()')
        except Exception:
            pass

        # ── 5d. Fix infinite recursion: add base-case stub ──
        if 'RecursionError' in issue_types:
            try:
                _tree4 = _ast2.parse(code)
                for _n in _ast2.walk(_tree4):
                    if isinstance(_n, (_ast2.FunctionDef, _ast2.AsyncFunctionDef)):
                        _calls_self = any(
                            isinstance(_c, _ast2.Call) and isinstance(_c.func, _ast2.Name) and _c.func.id == _n.name
                            for _c in _ast2.walk(_n)
                        )
                        _has_if = any(isinstance(_c, _ast2.If) for _c in _ast2.walk(_n))
                        if _calls_self and not _has_if:
                            fn_idx = _n.lineno  # line after def line
                            if fn_idx < len(fixed):
                                # Detect param name
                                _pname = _n.args.args[0].arg if _n.args.args else 'n'
                                _body_indent = ' ' * ((_n.col_offset or 0) + 4)
                                fixed.insert(fn_idx, _body_indent + f'    return {_pname}  # FIX: base case — remove or adjust this')
                                fixed.insert(fn_idx, _body_indent + f'if {_pname} <= 0:')
                                fixed.insert(fn_idx, _body_indent + f'# FIX: Added base case to prevent infinite recursion')
            except Exception:
                pass

        # ── 6. Fix bare input() — wrap with int()/float() + try/except ──
        # Find variables assigned from bare input() that are later used arithmetically
        whole_code = '\n'.join(fixed)
        for i, line in enumerate(fixed):
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            spc = ' ' * indent
            spc4 = ' ' * (indent + 4)

            # Pattern: var = input(...)  — bare, no int() or float() wrapping
            m_inp = re.match(r'^(\w+)\s*=\s*input\s*\((.+)\)\s*$', stripped)
            if m_inp:
                var = m_inp.group(1)
                prompt = m_inp.group(2)
                # Check if this variable is used in arithmetic/comparison in the rest of code
                rest = '\n'.join(fixed[i+1:])
                is_numeric = bool(re.search(
                    rf'{var}\s*[+\-*/%]|[+\-*/%]\s*{var}|'
                    rf'{var}\s*[<>]=?|[<>]=?\s*{var}|'
                    rf'int\s*\(\s*{var}\s*\)|float\s*\(\s*{var}\s*\)',
                    rest
                ))
                if is_numeric:
                    # Replace bare input() with try/except int(input(...))
                    replacement = [
                        spc + 'try:',
                        spc4 + f'{var} = int(input({prompt}))',
                        spc + 'except ValueError:',
                        spc4 + f'print("Please enter a valid integer")',
                        spc4 + f'{var} = 0  # default value'
                    ]
                    fixed[i:i+1] = replacement

        # ── 7. Fix == None / == True / == False → is None / is True / is False ──
        for i, line in enumerate(fixed):
            fixed[i] = re.sub(r'==\s*None\b', 'is None', fixed[i])
            fixed[i] = re.sub(r'!=\s*None\b', 'is not None', fixed[i])
            fixed[i] = re.sub(r'==\s*True\b', 'is True', fixed[i])
            fixed[i] = re.sub(r'==\s*False\b', 'is False', fixed[i])

        # ── 8. Add header comment ──
        fixed.insert(0, '# Auto-fixed by CodeDebug AI')

    elif language in ('javascript', 'typescript'):
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if not stripped or stripped.startswith('//'): continue
            indent = len(line) - len(line.lstrip())
            spc = ' ' * indent

            # Fix 1: == → === (type mismatch / loose equality)
            if re.search(r'(?<![=!<>])==(?!=)', stripped) and '===' not in stripped:
                fixed[i] = re.sub(r'(?<![=!<>])==(?!=)', '===', line)

            # Fix 2: var → let/const
            fixed[i] = re.sub(r'\bvar\b', 'let', fixed[i])

            # Fix 3: Missing semicolons on statement lines
            s = fixed[i].rstrip()
            if (s and not s.endswith((';', '{', '}', '(', ',', '*/'))
                    and not stripped.startswith(('//', '/*', '*'))
                    and not re.match(r'.*(if|else|for|while|function|class|=>)\s*[\({]?\s*$', s)):
                fixed[i] = s + ';'

            # Fix 4: async function without await — add comment
            if re.search(r'\basync\s+function\b', stripped):
                fn_block = '\n'.join(fixed[i+1:i+20])
                if 'await' not in fn_block:
                    fixed.insert(i+1, spc + '    // FIX: Add await before async calls inside this function')

            # Fix 5: infinite while(true) without break — add break stub
            if re.search(r'while\s*\(\s*(true|1)\s*\)', stripped):
                block = fixed[i+1:i+15]
                has_break = any('break' in l or 'return' in l for l in block)
                if not has_break:
                    # insert break stub inside loop
                    fixed.insert(i+1, spc + '    // FIX: Added break to prevent infinite loop — set your exit condition')
                    fixed.insert(i+2, spc + '    break; // TODO: replace with real exit condition')

        fixed.insert(0, '// [FIXED] Auto-fixed by CodeDebug AI')

    elif language in ('c', 'cpp', 'c++'):
        full = '\n'.join(fixed)
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if not stripped or stripped.startswith('//'): continue
            indent = len(line) - len(line.lstrip())
            spc = ' ' * indent

            # Fix 1: gets() → fgets()
            fixed[i] = re.sub(r'\bgets\s*\((\w+)\)', r'fgets(\1, sizeof(\1), stdin)', fixed[i])

            # Fix 2: scanf("%s") → scanf("%255s")
            fixed[i] = re.sub(r'scanf\s*\(\s*"([^"]*?)%s([^"]*?)"', r'scanf("\g<1>%255s\g<2>"', fixed[i])

            # Fix 3: Missing semicolons on statement lines
            s = fixed[i].rstrip()
            if (s and not s.endswith((';', '{', '}', '\\', ','))
                    and not stripped.startswith(('//', '/*', '*', '#'))
                    and not re.match(r'.*(if|else|for|while|do|switch)\s*[({]?\s*$', s)
                    and not re.match(r'^\s*(void|int|char|float|double|struct|class)\s+\w+\s*[({]', s)):
                fixed[i] = s + ';'

            # Fix 4: char array == comparison → strcmp
            m_cmp = re.search(r'(\w+)\s*==\s*"([^"]*)"', stripped)
            if m_cmp and re.search(r'\bchar\b', '\n'.join(fixed[:i+1])):
                var = m_cmp.group(1)
                val = m_cmp.group(2)
                fixed[i] = re.sub(
                    rf'{re.escape(var)}\s*==\s*"{re.escape(val)}"',
                    f'strcmp({var}, "{val}") == 0',
                    fixed[i]
                )

            # Fix 5: malloc without free — add free comment after last use
            if re.search(r'\bmalloc\s*\(', stripped) and 'free' not in full:
                m_var = re.search(r'(\w+)\s*=\s*malloc', stripped)
                if m_var:
                    fixed.insert(i+1, spc + f'// FIX: Remember to call free({m_var.group(1)}) when done')

        fixed.insert(0, '// [FIXED] Auto-fixed by CodeDebug AI')

    elif language == 'java':
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if not stripped or stripped.startswith('//'): continue
            indent = len(line) - len(line.lstrip())
            spc = ' ' * indent

            # Fix 1: str == "literal" → str.equals("literal")
            m = re.search(r'(\w+)\s*==\s*"([^"]*)"', stripped)
            if m:
                fixed[i] = re.sub(
                    rf'{re.escape(m.group(1))}\s*==\s*"{re.escape(m.group(2))}"',
                    f'{m.group(1)}.equals("{m.group(2)}")',
                    fixed[i]
                )

            # Fix 2: Missing semicolons
            s = fixed[i].rstrip()
            if (s and not s.endswith((';', '{', '}', ','))
                    and not stripped.startswith(('//', '/*', '*', '@'))
                    and not re.match(r'.*(class|interface|enum|if|else|for|while|do|try|catch|finally|switch)\b.*[{]?\s*$', s)):
                fixed[i] = s + ';'

            # Fix 3: int.parse → Integer.parseInt
            fixed[i] = re.sub(r'\bint\.parse\b', 'Integer.parseInt', fixed[i], flags=re.I)

            # Fix 4: catch (Exception) → catch (Exception e) with specific note
            if re.search(r'catch\s*\(\s*Exception\s*\)', stripped):
                fixed[i] = re.sub(r'catch\s*\(\s*Exception\s*\)', 'catch (Exception e)', fixed[i])
                fixed.insert(i+1, spc + '    // FIX: Use specific exception type e.g. IOException, NumberFormatException')

            # Fix 5: int overflow — int → long for large literals
            if re.search(r'\bint\s+\w+\s*=\s*\d{10,}', stripped):
                fixed[i] = re.sub(r'\bint\b', 'long', fixed[i], count=1)
                m_num = re.search(r'(\d{10,})', fixed[i])
                if m_num and not fixed[i].rstrip().endswith('L;'):
                    fixed[i] = re.sub(r'(\d{10,})', r'\1L', fixed[i])

        fixed.insert(0, '// [FIXED] Auto-fixed by CodeDebug AI')

    elif language == 'csharp':
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if not stripped or stripped.startswith('//'): continue
            spc = ' ' * (len(line) - len(line.lstrip()))

            # Fix: int.Parse → int.TryParse
            if re.search(r'\bint\.Parse\b', stripped):
                m_p = re.search(r'(\w+)\s*=\s*int\.Parse\(([^)]+)\)', stripped)
                if m_p:
                    var, expr = m_p.group(1), m_p.group(2)
                    fixed[i] = re.sub(
                        rf'{re.escape(var)}\s*=\s*int\.Parse\({re.escape(expr)}\)',
                        f'int.TryParse({expr}, out int {var}) ? {var} : 0',
                        fixed[i]
                    )

            # Fix: catch (Exception) — add variable
            if re.search(r'catch\s*\(\s*Exception\s*\)', stripped):
                fixed[i] = re.sub(r'catch\s*\(\s*Exception\s*\)', 'catch (Exception ex)', fixed[i])

            # Fix: Missing semicolons
            s = fixed[i].rstrip()
            if (s and not s.endswith((';', '{', '}', ','))
                    and not stripped.startswith(('//', '/*', '*', '['))
                    and not re.match(r'.*(class|interface|if|else|for|while|foreach|using|namespace|try|catch|finally)\b.*[{]?\s*$', s)):
                fixed[i] = s + ';'

        fixed.insert(0, '// [FIXED] Auto-fixed by CodeDebug AI')

    elif language == 'sql':
        for i, line in enumerate(fixed):
            stripped = line.strip()
            upper = stripped.upper()
            if not stripped or stripped.startswith('--'): continue

            # Fix: DELETE/UPDATE without WHERE — add warning comment
            if re.search(r'\b(DELETE\s+FROM|UPDATE\s+\w+\s+SET)\b', upper) and 'WHERE' not in upper:
                fixed.insert(i, '-- WARNING FIX: Added WHERE clause — remove or adjust the condition below')
                tbl = re.search(r'(?:FROM|UPDATE)\s+(\w+)', upper)
                tbl_name = tbl.group(1).lower() if tbl else 'table'
                fixed[i+1] = fixed[i+1].rstrip().rstrip(';') + f' WHERE id = 1; -- TODO: set real condition'

            # Fix: SELECT * → note
            if re.search(r'\bSELECT\s+\*\b', upper):
                fixed.insert(i, '-- FIX: Replace * with specific column names for better performance')

        fixed.insert(0, '-- [FIXED] Auto-fixed by CodeDebug AI')

    elif language == 'php':
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if not stripped or stripped.startswith('//'): continue
            spc = ' ' * (len(line) - len(line.lstrip()))

            # Fix: mysql_ → PDO comment
            if re.search(r'\bmysql_\w+\s*\(', stripped):
                fixed[i] = '// FIX: Replace mysql_* with PDO or mysqli (mysql_* removed in PHP7)\n' + fixed[i]

            # Fix: echo $_GET/POST unescaped → htmlspecialchars
            fixed[i] = re.sub(
                r'echo\s+(\$_(GET|POST|REQUEST)\[([^\]]+)\])',
                r'echo htmlspecialchars(\1, ENT_QUOTES, "UTF-8")',
                fixed[i]
            )

            # Fix: == → ===
            if re.search(r'(?<![=!<>])==(?!=)', stripped) and '===' not in stripped:
                fixed[i] = re.sub(r'(?<![=!<>])==(?!=)', '===', fixed[i])

        fixed.insert(0, '<?php // [FIXED] Auto-fixed by CodeDebug AI')

    elif language == 'go':
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if not stripped or stripped.startswith('//'): continue
            spc = ' ' * (len(line) - len(line.lstrip()))

            # Fix: discarded error _ → handle it
            if re.search(r',\s*_\s*:?=', stripped):
                fixed.insert(i+1, spc + '// FIX: Handle error instead of discarding with _')
                fixed.insert(i+2, spc + '// e.g. if err != nil { log.Fatal(err) }')

            # Fix: goroutine without sync
            if re.search(r'\bgo\s+\w+\(', stripped):
                full_code = '\n'.join(fixed)
                if 'WaitGroup' not in full_code and 'sync' not in full_code:
                    fixed.insert(i, spc + '// FIX: Use sync.WaitGroup or channel to wait for this goroutine')

        fixed.insert(0, '// [FIXED] Auto-fixed by CodeDebug AI')

    elif language == 'rust':
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if not stripped or stripped.startswith('//'): continue

            # Fix: .unwrap() → .unwrap_or_default()
            if re.search(r'\.unwrap\(\)', stripped):
                fixed[i] = re.sub(r'\.unwrap\(\)', '.unwrap_or_default()', fixed[i])
                fixed.insert(i, '// FIX: Changed unwrap() to unwrap_or_default() to prevent panic')

        fixed.insert(0, '// [FIXED] Auto-fixed by CodeDebug AI')

    elif language in ('ruby',):
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'): continue

            # Fix: rescue Exception → rescue StandardError
            if re.search(r'rescue\s+Exception\b', stripped):
                fixed[i] = re.sub(r'rescue\s+Exception\b', 'rescue StandardError', fixed[i])

        fixed.insert(0, '# [FIXED] Auto-fixed by CodeDebug AI')

    elif language in ('swift',):
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if not stripped or stripped.startswith('//'): continue

            # Fix: force unwrap ! → optional binding comment
            if re.search(r'\w+!(?!\s*=)', stripped) and '!=' not in stripped:
                fixed.insert(i, '// FIX: Avoid force unwrap ! — use if let or guard let instead')

            # Fix: var → let where possible
            if re.search(r'^\s*var\s+\w+\s*=', stripped):
                fixed.insert(i, '// FIX: Consider using let instead of var if this value never changes')

        fixed.insert(0, '// [FIXED] Auto-fixed by CodeDebug AI')

    elif language in ('kotlin',):
        for i, line in enumerate(fixed):
            stripped = line.strip()
            if not stripped or stripped.startswith('//'): continue

            # Fix: !! → safe call ?.
            if re.search(r'\w+!!', stripped):
                fixed[i] = re.sub(r'(\w+)!!', r'\1 ?: throw NullPointerException("FIX: was !!, handle null")', fixed[i])

            # Fix: var → val comment
            if re.search(r'^\s*var\s+\w+', stripped):
                fixed.insert(i, '// FIX: Consider val instead of var if not reassigned')

        fixed.insert(0, '// [FIXED] Auto-fixed by CodeDebug AI')

    return '\n'.join(fixed)




def generate_static_tips(issues: list, language: str) -> list:
    """Generate helpful optimization tips based on detected issues."""
    tips = []
    seen_types = {iss.get('type', '') for iss in issues}
    seen_msgs  = ' '.join(iss.get('message', '') for iss in issues).lower()

    if 'ZeroDivisionError' in seen_types:
        tips.append("Always validate inputs before performing division. Use `if divisor != 0:` or wrap with `try/except ZeroDivisionError`.")
    if 'TypeError' in seen_types:
        if 'argument' in seen_msgs:
            tips.append("Count function arguments carefully. Use your IDE's autocomplete to see required parameters.")
        if 'input' in seen_msgs or 'string' in seen_msgs:
            tips.append("Remember: `input()` always returns a string. Use `int(input())` or `float(input())` for numeric values.")
        if 'concatenate' in seen_msgs:
            tips.append("Use f-strings for mixing strings and numbers: `f\"Score: {score}\"` instead of `\"Score: \" + score`.")
        if 'callable' in seen_msgs:
            tips.append("Variables and functions are different. Don't use `()` after a variable that holds a value, not a function.")
    if 'RecursionError' in seen_types:
        tips.append("Every recursive function needs a base case (a condition to stop). Without it, recursion goes infinite.")
    if 'IndexError' in seen_types:
        tips.append("Always check list length before indexing: `if len(my_list) > index:` to prevent IndexError.")
    if 'RuntimeWarning' in seen_types:
        tips.append("Add input validation at the start of functions that perform arithmetic. This prevents runtime crashes.")
    if 'SyntaxError' in seen_types:
        tips.append("Use an IDE like VS Code with Python extension — it highlights syntax errors as you type.")
    if 'BestPractice' in seen_types:
        tips.append("Follow PEP 8 style guidelines to write cleaner, more readable Python code.")
    if 'LogicError' in seen_types:
        tips.append("Test edge cases: empty lists, zero values, and negative numbers to catch logic bugs early.")

    # General tips always shown
    tips.append("Write unit tests using Python's `unittest` or `pytest` to catch bugs automatically.")
    tips.append("Use descriptive variable names — `divisor` instead of `b` makes your code self-explanatory.")
    if language == 'python':
        tips.append("Consider using type hints: `def divide(a: float, b: float) -> float:` for better readability.")

    return tips


def build_ai_prompt(code: str, language: str, context: str = ""):
    return f"""You are an expert code debugger and teacher. Analyze the following {language} code and provide a comprehensive debugging report.

IMPORTANT: Respond ONLY with valid JSON in the exact format below. Do not include any markdown, code fences, or explanation outside the JSON.

Code to analyze:
```{language}
{code}
```

{f"Additional context: {context}" if context else ""}

Respond with this exact JSON structure:
{{
  "summary": "Brief one-sentence summary of the code's purpose and overall health",
  "overall_score": 75,
  "errors": [
    {{
      "line": 5,
      "type": "SyntaxError",
      "severity": "error",
      "message": "Short title of the error",
      "description": "Beginner-friendly explanation of why this is wrong",
      "fix": "How to fix this in simple terms"
    }}
  ],
  "corrected_code": "The complete corrected version of the code",
  "optimizations": [
    "Tip 1: Specific optimization suggestion",
    "Tip 2: Another suggestion"
  ],
  "concepts_explained": [
    {{
      "concept": "Name of the concept",
      "explanation": "Simple explanation of what this concept is and why it matters"
    }}
  ],
  "complexity": {{
    "time": "O(n) explanation",
    "space": "O(1) explanation"
  }}
}}

Severity levels: "error" (breaks execution), "warning" (may cause bugs), "info" (best practice), "success" (good code)
overall_score: 0-100 (100 = perfect code)
Be beginner-friendly. Explain errors like you're teaching a student who is learning to code.
If no errors found, return empty errors array and score of 100."""


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/analyze', methods=['POST'])
def analyze_code():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    code = data.get('code', '').strip()
    language = data.get('language', 'python').lower()
    context = data.get('context', '')

    if not code:
        return jsonify({"error": "No code provided"}), 400

    if len(code) > 20000:
        return jsonify({"error": "Code too long. Maximum 20,000 characters."}), 400

    # Static analysis
    static_issues = []
    if language == 'python':
        static_issues = analyze_python_static(code)
    pattern_issues = detect_common_patterns(code, language)
    all_static = static_issues + pattern_issues

    # AI Analysis
    ai_result = None
    if AI_AVAILABLE and _client:
        try:
            prompt = build_ai_prompt(code, language, context)
            response = _client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )
            raw = response.text.strip()
            # Strip markdown fences if present
            raw = re.sub(r'^```[a-z]*\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
            ai_result = json.loads(raw)
        except json.JSONDecodeError:
            ai_result = None
        except Exception as e:
            ai_result = {"error": str(e)}

    # Build final response
    if ai_result and "errors" in ai_result:
        # Merge static issues that AI might have missed
        ai_lines = {e.get('line') for e in ai_result['errors']}
        for si in all_static:
            if si.get('line') not in ai_lines:
                ai_result['errors'].append(si)
        return jsonify({
            "success": True,
            "source": "ai",
            "language": language,
            "result": ai_result,
            "static_issues": all_static
        })
    else:
        # Fallback to static-only with built-in code fixer
        # Severity-weighted score: errors -25, warnings -10, info -5
        deduction = sum(
            25 if i.get('severity') == 'error' else
            10 if i.get('severity') == 'warning' else 5
            for i in all_static
        )
        score = max(0, 100 - deduction)
        fixed_code = generate_fixed_code(code, language, all_static)
        tips = generate_static_tips(all_static, language)
        err_count = len(all_static)
        summary = (
            f"Found {err_count} issue(s) in your {language} code. "
            "Auto-fix applied below — review it carefully."
        ) if err_count else f"Your {language} code looks clean! No issues detected."
        return jsonify({
            "success": True,
            "source": "static",
            "language": language,
            "result": {
                "summary": summary,
                "overall_score": score,
                "errors": all_static,
                "corrected_code": fixed_code,
                "optimizations": tips,
                "concepts_explained": [],
                "complexity": {"time": "N/A", "space": "N/A"}
            },
            "static_issues": all_static
        })


@app.route('/api/languages', methods=['GET'])
def get_languages():
    return jsonify({
        "languages": [
            {"id": "python", "name": "Python", "icon": "🐍"},
            {"id": "javascript", "name": "JavaScript", "icon": "🌐"},
            {"id": "typescript", "name": "TypeScript", "icon": "📘"},
            {"id": "java", "name": "Java", "icon": "☕"},
            {"id": "cpp", "name": "C++", "icon": "⚙️"},
            {"id": "c", "name": "C", "icon": "🔧"},
            {"id": "csharp", "name": "C#", "icon": "💜"},
            {"id": "go", "name": "Go", "icon": "🐹"},
            {"id": "rust", "name": "Rust", "icon": "🦀"},
            {"id": "php", "name": "PHP", "icon": "🐘"},
            {"id": "ruby", "name": "Ruby", "icon": "💎"},
            {"id": "swift", "name": "Swift", "icon": "🍎"},
            {"id": "kotlin", "name": "Kotlin", "icon": "🎯"},
            {"id": "sql", "name": "SQL", "icon": "🗃️"}
        ]
    })


@app.route('/api/examples', methods=['GET'])
def get_examples():
    return jsonify({
        "examples": [
            {
                "id": "py_syntax",
                "title": "Python - Syntax Error",
                "language": "python",
                "code": """def calculate_average(numbers)
    total = 0
    for num in numbers:
        total += num
    average = total / len(numbers)
    return average

scores = [85, 92, 78, 96, 88]
result = calculate_average(scores)
print("Average:", result)"""
            },
            {
                "id": "py_logic",
                "title": "Python - Logic Error",
                "language": "python",
                "code": """def find_max(numbers):
    max_val = 0
    for num in numbers:
        if num > max_val:
            max_val = num
    return max_val

# Bug: fails for all-negative lists
numbers = [-5, -2, -8, -1]
print("Max:", find_max(numbers))"""
            },
            {
                "id": "py_divzero",
                "title": "Python - Divide by Zero",
                "language": "python",
                "code": """def divide_numbers(a, b):
    result = a / b
    return result

print(divide_numbers(10, 0))"""
            },
            {
                "id": "py_boundary",
                "title": "Python - Boundary Bug",
                "language": "python",
                "code": """# Voting eligibility checker
age = 18

if age > 18:
    print("You are eligible to vote")
else:
    print("You are not eligible to vote")"""
            },
            {
                "id": "py_returnprint",
                "title": "Python - Return Print Bug",
                "language": "python",
                "code": """def get_greeting(name):
    return print("Hello, " + name)

message = get_greeting("Alice")
print("Got:", message)"""
            },
            {
                "id": "py_input",
                "title": "Python - Input Crash",
                "language": "python",
                "code": """# Calculator without error handling
num1 = int(input("Enter first number: "))
num2 = int(input("Enter second number: "))
result = num1 / num2
print("Result:", result)"""
            },
            {
                "id": "py_unreachable",
                "title": "Python - Unreachable Code",
                "language": "python",
                "code": """def check_password(password):
    if len(password) < 8:
        return "Too short"
    return "Valid"
    print("Password checked!")
    x = 42"""
            },
            {
                "id": "js_common",
                "title": "JavaScript - Common Mistakes",
                "language": "javascript",
                "code": """// Bug 1: == instead of ===
var x = "5";
var y = 5;
if (x == y) {
    console.log("Equal?");
}

// Bug 2: var hoisting
function processData() {
    console.log(data);
    var data = "hello";
}

// Bug 3: unreachable code
function add(a, b) {
    return
    a + b
}

console.log(add(2, 3));"""
            },
            {
                "id": "java_string",
                "title": "Java - String Comparison",
                "language": "java",
                "code": """public class StudentGrade {
    public static String getGrade(int score) {
        String grade;
        if (score >= 90) grade = "A";
        else if (score >= 80) grade = "B";
        else grade = "F";
        return grade;
    }

    public static void main(String[] args) {
        String grade = getGrade(85);

        // Bug: Using == for String comparison
        if (grade == "B") {
            System.out.println("Good job!");
        } else {
            System.out.println("Keep trying!");
        }
    }
}"""
            },
            {
                "id": "cpp_memory",
                "title": "C++ - Memory Management",
                "language": "cpp",
                "code": """#include <iostream>
#include <cstring>
using namespace std;

void getUserInput() {
    char buffer[10];
    // Bug: gets() is unsafe
    gets(buffer);
    cout << "You entered: " << buffer << endl;
}

int* createArray(int size) {
    int* arr = new int[size];
    for (int i = 0; i < size; i++) {
        arr[i] = i * 2;
    }
    return arr;
    // Bug: memory never freed
}

int main() {
    getUserInput();
    int* data = createArray(5);
    cout << data[0] << endl;
    // Missing: delete[] data;
    return 0;
}"""
            }
        ]
    })


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "running",
        "ai_available": AI_AVAILABLE,
        "version": "2.0.0"
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
