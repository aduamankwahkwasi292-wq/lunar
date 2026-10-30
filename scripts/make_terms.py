"""
Build the copies of MrSOLIS's Terms of Use that students see, from the one source, TERMS-OF-USE.md:

    python scripts/make_terms.py

  desktop/build/license.txt                    the installer's "License Agreement" page (NSIS; plain ASCII text)
  frontend/static/licences/terms-of-use.html   Settings → About → Terms of use, in the app

Everything between <!-- owner --> and <!-- /owner --> (the draft note, the owner's notes) is left out.
Run it after every change to TERMS-OF-USE.md.
"""
import html
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "TERMS-OF-USE.md")
TXT = os.path.join(ROOT, "desktop", "build", "license.txt")
HTML = os.path.join(ROOT, "frontend", "static", "licences", "terms-of-use.html")
ASCII = {"—": "--", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "·": "-", "…": "...", "→": "->", "©": "(c)"}


def shown_text():
    s = open(SRC, encoding="utf-8").read()
    return re.sub(r"<!-- owner -->.*?<!-- /owner -->\n?", "", s, flags=re.S).strip() + "\n"


def blocks(md):
    """[(kind, text)]: h1/h2/h3, hr, quote, item (with its marker), para — continuation lines joined."""
    out = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            out.append(("gap", ""))
            continue
        m = re.match(r"^(#{1,3}) (.*)", line)
        if m:
            out.append((f"h{len(m[1])}", m[2]))
        elif line.strip() == "---":
            out.append(("hr", ""))
        elif line.startswith("> "):
            out.append(("quote", line[2:]))
        elif re.match(r"^\s*(\d+\.|-|\([a-z]\)) ", line):
            m = re.match(r"^(\s*)(\d+\.|-|\([a-z]\)) (.*)", line)
            out.append(("item", (len(m[1]), m[2], m[3])))
        elif out and out[-1][0] in ("item", "para", "quote"):          # a wrapped line continues the last block
            kind, val = out[-1]
            if kind == "item":
                out[-1] = ("item", (val[0], val[1], val[2] + " " + line.strip()))
            else:
                out[-1] = (kind, val + " " + line.strip())
        else:
            out.append(("para", line.strip()))
    return [b for b in out if b[0] != "gap"]


def inline(text):
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


def to_html(md):
    parts, open_list = [], None
    for kind, val in blocks(md):
        if kind != "item" and open_list:
            parts.append(f"</{open_list[0]}>")
            open_list = None
        if kind in ("h1", "h2", "h3"):
            parts.append(f"<{kind}>{inline(val)}</{kind}>")
        elif kind == "hr":
            parts.append("<hr>")
        elif kind == "quote":
            parts.append(f"<blockquote>{inline(val)}</blockquote>")
        elif kind == "para":
            parts.append(f"<p>{inline(val)}</p>")
        else:
            indent, marker, text = val
            tag = "ul" if marker == "-" else "ol"
            cls = "letters" if marker.startswith("(") else ("sub" if indent else "")
            if open_list != (tag, cls):
                if open_list:
                    parts.append(f"</{open_list[0]}>")
                parts.append(f'<{tag} class="{cls}">')
                open_list = (tag, cls)
            label = f'<span class="m">{marker}</span> ' if marker.startswith("(") else ""
            number = f' value="{marker[:-1]}"' if marker[:-1].isdigit() else ""   # 5. after a sub-list stays 5.
            parts.append(f"<li{number}>{label}{inline(text)}</li>")
    if open_list:
        parts.append(f"</{open_list[0]}>")
    return "\n".join(parts) + "\n"


def to_text(md):
    lines = []
    for kind, val in blocks(md):
        if kind in ("h1", "h2", "h3"):
            title = re.sub(r"\*\*(.+?)\*\*", r"\1", val)
            lines += ["", title.upper() if kind != "h3" else title, ""]
        elif kind == "hr":
            lines += [""]
        elif kind in ("para", "quote"):
            lines += [re.sub(r"\*\*(.+?)\*\*|`(.+?)`", lambda m: m[1] or m[2], val), ""]
        else:
            indent, marker, text = val
            text = re.sub(r"\*\*(.+?)\*\*|`(.+?)`", lambda m: m[1] or m[2], text)
            lines += [" " * indent + f"{marker} {text}"]
    txt = "\n".join(lines).strip() + "\n"
    for k, v in ASCII.items():
        txt = txt.replace(k, v)
    return txt.encode("ascii", "replace").decode("ascii").replace("\n", "\r\n")


def main():
    md = shown_text()
    os.makedirs(os.path.dirname(TXT), exist_ok=True)
    with open(TXT, "w", encoding="ascii", newline="") as f:
        f.write(to_text(md))
    with open(HTML, "w", encoding="utf-8") as f:
        f.write(to_html(md))
    print(f"wrote {TXT} and {HTML}")


if __name__ == "__main__":
    main()
