"""
calculator.py — spoken-math engine for NirmiqEcho

Turns natural spoken arithmetic into a real answer, 100% offline and
deterministic (no LLM, no eval-injection risk — a restricted AST walker).

Handles, e.g.:
    "add 45 and 30"                 -> 75
    "what is 12 times 8"            -> 96
    "50 divided by 5"              -> 10
    "what's 100 minus 37"          -> 63
    "15 percent of 200"            -> 30
    "square root of 144"           -> 12
    "2 to the power of 10"         -> 1024
    "7 squared"                    -> 49
    "(3 plus 4) times 5"           -> 35
"""
import ast
import math
import operator
import re
from typing import Optional, Tuple

# Word → digit for small spoken numbers Whisper may spell out
_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
    "thousand": 1000, "million": 1000000,
}

# Spoken operator → symbol
_OP_WORDS = [
    (r"\bplus\b|\band\b(?=\s*\d)|\badded to\b", "+"),
    (r"\bminus\b|\bsubtract(?:ed)?(?:\s+from)?\b|\bless\b", "-"),
    (r"\btimes\b|\bmultiplied by\b|\bmultiply(?:\s+by)?\b|\bx\b(?=\s*\d)", "*"),
    (r"\bdivided by\b|\bdivide(?:\s+by)?\b|\bover\b", "/"),
    (r"\bto the power of\b|\braised to\b|\bpower\b", "**"),
    (r"\bmod(?:ulo|ulus)?\b", "%"),
]

# Restricted set of allowed AST operators (no names, calls, attributes)
_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _words_to_numbers(text: str) -> str:
    """Replace standalone number words with digits (basic, additive)."""
    def repl(m):
        return str(_WORD_NUMBERS[m.group(0).lower()])
    pattern = r"\b(" + "|".join(_WORD_NUMBERS) + r")\b"
    return re.sub(pattern, repl, text, flags=re.IGNORECASE)


def spoken_to_expr(text: str) -> Optional[str]:
    """
    Convert a spoken-math phrase to an arithmetic expression string.
    Returns None if it doesn't look like math.
    """
    t = text.lower().strip().rstrip("?.!")

    # Strip lead-ins
    t = re.sub(r"^(?:hey\s+)?(?:echo[,\s]+)?", "", t)
    t = re.sub(r"^(?:what(?:'s|\s+is)|how much is|calculate|compute|"
               r"work out|tell me)\s+", "", t)

    # Special forms first
    m = re.search(r"square root of\s+(.+)", t)
    if m:
        inner = spoken_to_expr(m.group(1)) or _words_to_numbers(m.group(1))
        return f"({inner})**0.5"
    m = re.search(r"(.+?)\s+squared\b", t)
    if m:
        inner = spoken_to_expr(m.group(1)) or _words_to_numbers(m.group(1))
        return f"({inner})**2"
    m = re.search(r"(.+?)\s+cubed\b", t)
    if m:
        inner = spoken_to_expr(m.group(1)) or _words_to_numbers(m.group(1))
        return f"({inner})**3"
    # "15 percent of 200" -> 15/100*200
    m = re.search(r"(.+?)\s+percent of\s+(.+)", t)
    if m:
        a = _words_to_numbers(m.group(1)).strip()
        b = _words_to_numbers(m.group(2)).strip()
        return f"({a})/100*({b})"

    # General: replace operator words, number words, keep digits/symbols/parens
    t = _words_to_numbers(t)
    for pat, sym in _OP_WORDS:
        t = re.sub(pat, f" {sym} ", t)

    # "add X and Y" pattern already handled by 'and'->'+' when near a digit;
    # also handle leading "add/sum/subtract/multiply/divide"
    t = re.sub(r"^\s*(?:add|sum(?:\s+up)?)\s+", "", t)
    t = re.sub(r"^\s*subtract\s+", "", t)

    # keep only math-safe characters
    cleaned = re.sub(r"[^0-9+\-*/%.()\s]", "", t)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Must contain at least one digit and one operator to be "math"
    if not re.search(r"\d", cleaned):
        return None
    if not re.search(r"[+\-*/%]|\*\*", cleaned):
        return None
    return cleaned


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):          # numbers
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("non-numeric constant")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"disallowed expression: {ast.dump(node)}")


def safe_eval(expr: str) -> float:
    """Evaluate an arithmetic expression with a restricted AST (no code exec)."""
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree)


def _format(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def calculate(text: str) -> Optional[Tuple[str, str]]:
    """
    Try to compute a spoken-math phrase.
    Returns (result_str, spoken_str) or None if not a math request.
    """
    expr = spoken_to_expr(text)
    if not expr:
        return None
    try:
        value = safe_eval(expr)
    except (ZeroDivisionError,):
        return ("undefined", "That's undefined — you can't divide by zero.")
    except Exception:
        return None
    result = _format(value)
    return (result, f"The answer is {result}.")


# ─────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cases = {
        "add 45 and 30": "75",
        "what is 12 times 8": "96",
        "50 divided by 5": "10",
        "what's 100 minus 37": "63",
        "15 percent of 200": "30",
        "square root of 144": "12",
        "2 to the power of 10": "1024",
        "7 squared": "49",
        "calculate 3 plus 4 times 5": "23",
        "what is twelve plus eight": "20",
        "100 divided by 4": "25",
        "9 times 9": "81",
    }
    passed = 0
    for phrase, want in cases.items():
        got = calculate(phrase)
        result = got[0] if got else None
        ok = result == want
        passed += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {phrase!r:40} -> {result} (want {want})")
    print(f"\n{passed}/{len(cases)} passed")
    # ensure non-math is rejected
    assert calculate("open chrome") is None
    assert calculate("what time is it") is None
    print("non-math correctly rejected")
