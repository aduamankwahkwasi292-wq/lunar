"""Lunar AI backend package."""

# Before anything parses maths: SymPy's text parsing can't run code (backend/safemath.py).
try:
    from backend import safemath as _safemath
    _safemath.install()
except ImportError:          # SymPy missing: nothing to protect
    pass
