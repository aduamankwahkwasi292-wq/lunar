"""
Maths text is evaluated safely (hardening, 2026-10-29).

SymPy turns text into maths with Python's eval(): sympify("x + 1") and parse_expr(...) run the text as code, with
eval, exec, open and __import__ in reach. MrSOLIS parses text it didn't write — formulas from slides, the brain's
answers, photos, a question pasted from a chat — so a booby-trapped slide deck could have run a program on the
student's computer. install() closes that for every caller at once (SymPy looks both functions up at call time):

  - stringify_expr: the code made from the text must be plain maths — no double underscores, no attribute access
    (x.y), no backslashes, no f-strings — else the parse fails like any other bad input (ValueError);
  - eval_expr: the code runs with no Python built-ins at all, and without SymPy's few helpers that run code of
    their own (lambdify, plotting, preview, the test runner...).

Nested parses (sympify called on a string inside the text) go through the same two checks.
"""
from __future__ import annotations

import builtins
import re
import unicodedata

_SAFE_BUILTINS = {"abs", "divmod", "max", "min", "pow", "round", "sum"}    # max / min are SymPy's Max / Min here
_DENY = re.compile(r"^(?:lambdify|lambdastr|implemented_function|var|preview|test|doctest|init_\w+|plot\w*|"
                   r"textplot|dotprint|source|interactive_traversal|import_module|ufuncify|autowrap|print_\w+|"
                   r"pprint\w*|pretty_print)$")
_ATTR = re.compile(r"\.\s*[^\W\d]")                       # x.y; a decimal point is followed by a digit
_FSTRING = re.compile(r"(?<![\w'\"])(?:[fF][rRbB]?|[rRbB][fF])['\"]")
_BUILTIN_NAMES = frozenset(vars(builtins))
_installed = False


def unsafe(code) -> str:
    """Why this can't be maths for SymPy to evaluate ('' when it is fine)."""
    c = unicodedata.normalize("NFKC", str(code))           # Python reads ＿＿ as __ and ｅｘｅｃ as exec
    if "__" in c:
        return "double underscore"
    if "\\" in c:
        return "backslash"
    if _ATTR.search(c):
        return "attribute access"
    if _FSTRING.search(c):
        return "f-string"
    return ""


def clean_globals(global_dict) -> dict:
    out = {k: v for k, v in (global_dict or {}).items()
           if not (k.startswith("_") or (k in _BUILTIN_NAMES and k not in _SAFE_BUILTINS) or _DENY.match(k))}
    out["__builtins__"] = {}
    return out


def install() -> None:
    global _installed
    if _installed:
        return
    from sympy.parsing import sympy_parser as sp
    stringify, evaluate = sp.stringify_expr, sp.eval_expr

    def stringify_expr(s, local_dict, global_dict, transformations):
        code = stringify(s, local_dict, global_dict, transformations)
        why = unsafe(code)
        if why:
            raise ValueError(f"not maths ({why})")
        return code

    def eval_expr(code, local_dict, global_dict):
        return evaluate(code, local_dict, clean_globals(global_dict))

    sp.stringify_expr, sp.eval_expr = stringify_expr, eval_expr
    _installed = True
