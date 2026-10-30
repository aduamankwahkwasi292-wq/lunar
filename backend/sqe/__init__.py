"""
CUSTOM-SQE: MrSOLIS's similar-questions engine (the SQE window, opened from Quizzes).

A student types ONE maths question they already have. CUSTOM-SQE works out what kind of question it is, makes
fresh versions by changing its numbers, and works every answer out again with sympy, so the answers are
computed, never guessed. There are no brain (LLM) calls anywhere in it.

Built from the user's MrSOLIS 2-AL engine (Downloads\\mrsolis-2-al\\pp\\qgen, 2026-08). The original is unchanged;
this copy drops what MrSOLIS doesn't need: the PowerPoint/PDF readers, the scikit-learn near-duplicate filter
(off in 2-AL too) and the SQLite store (a practice session's "never repeat" memory is kept in memory).
"""
__version__ = "1.0.0"
