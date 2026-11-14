"""
JSON shapes as llama.cpp grammars (GBNF), for a brain that must answer in JSON from its very first token.

Why (2026-11-13): Smarts (Gemma 4 E4B) opens a hidden "thought" section by itself, even with thinking off. With
`response_format`, llama-server's chat parser for Gemma lets that section come before the JSON — 4 of 30 quiz
questions came back empty, and with its opening token banned Gemma spelled the opener out in plain letters. So
Smarts' engine runs with `--skip-chat-parsing` (everything it writes is the answer) and its JSON replies carry a
grammar of their own, which the engine applies from the first token: the reply can only be the JSON. In that mode
llama-server ignores `response_format` and rejects `json_schema` (it feeds the turn marker through the grammar), so
the app writes the grammar itself — llama.cpp's own Python converter is gone from its repo (b11721).

Covers the shapes MrSOLIS sends (quizgen, the CUSTOM-Mx reader): objects whose properties are all required,
strings (maxLength), string enums, booleans, numbers, integers, arrays (items, minItems, maxItems). Anything else
falls back to "any JSON object", which still can't start with a thought. Whitespace follows llama.cpp's converter
(a space, or a new line and up to 20 spaces/tabs, between tokens), so the brain can lay JSON out as it likes.
"""

import json

_SPACE = 'space ::= | " " | "\\n" [ \\t]{0,20}'
_CHAR = 'char ::= [^"\\\\\\x7F\\x00-\\x1F] | [\\\\] (["\\\\bfnrt] | "u" [0-9a-fA-F]{4})'
_STRING = 'string ::= "\\"" char* "\\"" space'
_NUMBER = ('number ::= "-"? ([0-9] | [1-9] [0-9]{0,15}) ("." [0-9]{1,16})? ([eE] [-+]? [0-9]{1,16})? space')
_INTEGER = 'integer ::= "-"? ([0-9] | [1-9] [0-9]{0,15}) space'
_BOOLEAN = 'boolean ::= ("true" | "false") space'
_ANY = [
    'value ::= object | array | string | number | ("true" | "false" | "null") space',
    'object ::= "{" space ( string ":" space value ("," space string ":" space value)* )? "}" space',
    'array ::= "[" space ( value ("," space value)* )? "]" space',
]
ANY_OBJECT = "\n".join(["root ::= object", *_ANY, _STRING, _CHAR, _NUMBER, _SPACE])


class _Unsupported(Exception):
    pass


def _lit(s: str) -> str:
    """A GBNF literal that matches the JSON text of `s` (with its quotes) exactly."""
    j = json.dumps(s, ensure_ascii=False)
    return '"' + j.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'


class _Builder:
    def __init__(self):
        self.rules, self.n = [], 0

    def rule(self, body: str) -> str:
        self.n += 1
        name = f"r{self.n}"
        self.rules.append(f"{name} ::= {body}")
        return name

    def value(self, s: dict) -> str:
        if not isinstance(s, dict):
            raise _Unsupported("schema")
        if "enum" in s:
            vals = s["enum"]
            if not vals or not all(isinstance(v, str) for v in vals):
                raise _Unsupported("enum")
            return self.rule("(" + " | ".join(_lit(v) for v in vals) + ") space")
        t = s.get("type")
        if t == "string":
            if set(s) - {"type", "maxLength", "description"}:
                raise _Unsupported("string")
            n = s.get("maxLength")
            return self.rule(f'"\\"" char{{0,{int(n)}}} "\\"" space') if n is not None else "string"
        if t == "boolean":
            return "boolean"
        if t == "number":
            return "number"
        if t == "integer":
            return "integer"
        if t == "array":
            if set(s) - {"type", "items", "minItems", "maxItems", "description"}:
                raise _Unsupported("array")
            item = self.value(s.get("items") or {"type": "string"})
            lo, hi = int(s.get("minItems", 0)), s.get("maxItems")
            if hi is not None and int(hi) < max(lo, 1):
                raise _Unsupported("array bounds")
            more_lo = max(lo - 1, 0)
            more = f"{{{more_lo},{int(hi) - 1}}}" if hi is not None else (f"{{{more_lo},}}" if more_lo else "*")
            body = f'{item} ("," space {item}){more}'
            return self.rule(f'"[" space {body} "]" space' if lo >= 1 else f'"[" space ({body})? "]" space')
        if t == "object":
            props = s.get("properties") or {}
            if not props or set(s.get("required") or []) != set(props) \
                    or set(s) - {"type", "properties", "required", "additionalProperties", "description"}:
                raise _Unsupported("object")
            parts = [f'{_lit(k)} space ":" space {self.value(v)}' for k, v in props.items()]
            return self.rule('"{" space ' + ' "," space '.join(parts) + ' "}" space')
        raise _Unsupported(str(t))


def from_schema(schema) -> str:
    """The GBNF for replies of this JSON shape (root = the shape); "any JSON object" when the shape is beyond it."""
    b = _Builder()
    try:
        root = b.value(schema)
    except (_Unsupported, TypeError, ValueError):
        return ANY_OBJECT
    return "\n".join([f"root ::= {root}", *b.rules, _STRING, _CHAR, _NUMBER, _INTEGER, _BOOLEAN, _SPACE])
