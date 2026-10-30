"""
Draw PowerPoint slides as pictures without PowerPoint.

This is the fallback for computers with no office suite (file_processor.office_to_pdf found
none). python-pptx reads the deck and this module paints each slide the way PowerPoint lays
it out:
  - the background (slide, else its layout, else the master);
  - the template's own shapes — logos, banners — under the slide's;
  - pictures (cropped as on the slide), shapes with their fills and outlines, tables, groups;
  - text with its real fonts, sizes, colours, bold/italic/underline, alignment, bullets and
    numbering, line spacing and auto-shrink, following PowerPoint's inheritance (the slide's
    placeholder → its layout → the master → the master's text styles) and the theme's
    colours and fonts.
SmartArt is drawn from the shapes PowerPoint saves alongside it; charts become a labelled
box. Every word's box is recorded too, so the slide's text can be selected on the board.

It won't match PowerPoint pixel for pixel (no 3-D, effects, or exotic shapes), but slides
keep their layout, colours and pictures.
"""

import colorsys
import io
import math
import os
import re
import sys
import threading

from PIL import Image, ImageDraw, ImageFont

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
RT_THEME = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
RT_DIAGRAM_DRAWING = "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing"
RT_CHART = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart"

OUT_WIDTH = 1600          # final picture width (px); drawn at 2× and scaled down for smooth edges
SS = 2
EMU_PER_PT = 12700


def _a(tag):
    return "{%s}%s" % (A, tag)


def _p(tag):
    return "{%s}%s" % (P, tag)


def _local(el):
    t = el.tag
    return t.rsplit("}", 1)[-1] if isinstance(t, str) else ""


def _kid(el, name):
    """First child with this local name (any namespace — SmartArt drawings use their own)."""
    if el is None:
        return None
    for c in el:
        if _local(c) == name:
            return c
    return None


def _kids(el, name):
    return [c for c in el if _local(c) == name] if el is not None else []


def _path(el, *names):
    for n in names:
        el = _kid(el, n)
        if el is None:
            return None
    return el


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ══════════════════════════════════════════════════════════════════════
#   fonts
# ══════════════════════════════════════════════════════════════════════
_FONT_DIRS = []
if sys.platform == "win32":
    _FONT_DIRS += [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
                   os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
                   # Microsoft 365 "cloud fonts" (Aptos, the new Office default, lives here)
                   os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "FontCache", "4", "CloudFonts")]
elif sys.platform == "darwin":
    _FONT_DIRS += ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
                   os.path.expanduser("~/Library/Fonts")]
else:
    _FONT_DIRS += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
                   os.path.expanduser("~/.local/share/fonts")]

# what to use when a deck's font isn't installed
_FONT_FALLBACK = {
    "calibri": ["carlito"], "calibri light": ["calibri", "carlito"], "cambria": ["caladea", "times new roman"],
    "century gothic": ["urw gothic", "avenir", "arial"], "segoe ui": ["arial"], "helvetica": ["arial"],
    "times": ["times new roman"], "candara": ["calibri"], "corbel": ["calibri"], "tw cen mt": ["century gothic", "arial"],
    "gill sans mt": ["gill sans", "calibri"], "franklin gothic book": ["arial"], "verdana": ["dejavu sans"],
    "aptos": ["segoe ui", "calibri"], "aptos display": ["segoe ui semibold", "segoe ui", "calibri"],
    "aptos black": ["arial black", "segoe ui black"], "aptos narrow": ["arial narrow", "calibri"],
    "aptos light": ["segoe ui light", "calibri light"], "aptos semibold": ["segoe ui semibold", "calibri"],
}
_GENERIC = ["arial", "liberation sans", "dejavu sans", "helvetica", "segoe ui"]


class _Fonts:
    """Family name → font files, found once by reading the fonts' own names (cached to disk)."""

    def __init__(self):
        self._map = None
        self._lock = threading.Lock()
        self._cache = {}

    def _scan(self):
        import json
        import tempfile
        files = []
        for d in _FONT_DIRS:
            if not os.path.isdir(d):
                continue
            for top, _, names in os.walk(d):
                for n in names:
                    if n.lower().endswith((".ttf", ".otf", ".ttc")):
                        files.append(os.path.join(top, n))
        sig = f"v2:{len(files)}:{max((os.path.getmtime(f) for f in files), default=0):.0f}"
        cache = os.path.join(tempfile.gettempdir(), "mrsolis_fonts.json")
        try:
            data = json.load(open(cache, encoding="utf-8"))
            if data.get("sig") == sig:
                return {k: {s: v for s, v in d.items()} for k, d in data["map"].items()}
        except Exception:
            pass
        fmap = {}
        for f in files:
            try:
                fam, style = ImageFont.truetype(f, 12).getname()
            except Exception:
                continue
            if not fam:
                continue
            st = (style or "").strip().lower()
            italic = "italic" in st or "oblique" in st
            weight = st.replace("italic", "").replace("oblique", "").strip()
            if weight in ("", "regular", "normal", "book", "roman", "bold"):
                key = ("b" if weight == "bold" else "") + ("i" if italic else "")
                fmap.setdefault(fam.lower(), {}).setdefault(key or "r", f)
            else:
                # "Arial" + "Black" is the font decks ask for as "Arial Black" (likewise Semibold, Light…)
                fmap.setdefault(f"{fam} {weight}".lower(), {}).setdefault("i" if italic else "r", f)
        try:
            json.dump({"sig": sig, "map": fmap}, open(cache, "w", encoding="utf-8"))
        except Exception:
            pass
        return fmap

    def path(self, family, bold=False, italic=False):
        with self._lock:
            if self._map is None:
                self._map = self._scan()
        fam = (family or "").lower().strip()
        tries = [fam] + _FONT_FALLBACK.get(fam, [])
        if fam not in self._map:
            # a font this computer lacks: something of the same kind
            if re.search(r"mono|courier|consolas|code|typewriter|fixed", fam):
                tries += ["consolas", "courier new", "dejavu sans mono", "liberation mono", "menlo"]
            elif re.search(r"serif|times|georgia|garamond|roman|antiqua|cambria|baskerville|bookman|palatino", fam) \
                    and "sans" not in fam:
                tries += ["times new roman", "georgia", "cambria", "liberation serif", "dejavu serif"]
            tries += [k for k in ("arial", "calibri", "segoe ui", "verdana", "tahoma", "century gothic", "gill sans")
                      if k in fam]                     # "Akan Arial" → Arial
        tries += _GENERIC
        want = ("b" if bold else "") + ("i" if italic else "") or "r"
        for t in tries:
            styles = self._map.get(t)
            if styles:
                for k in (want, want.replace("i", "") or "r", "r", *styles.keys()):
                    if k in styles:
                        return styles[k], (k != want and bold and "b" not in k)
        return None, bold

    def has(self, family):
        with self._lock:
            if self._map is None:
                self._map = self._scan()
        return (family or "").lower().strip() in self._map

    def get(self, family, size_px, bold=False, italic=False, symbol=False):
        size_px = max(1, int(round(size_px)))
        key = (family, size_px, bold, italic, symbol)
        f = self._cache.get(key)
        if f is None:
            path, fake_bold = self.path(family, bold, italic)
            try:
                f = (ImageFont.truetype(path, size_px, encoding="symb" if symbol else "") if path
                     else ImageFont.load_default(size_px))            # symbol fonts map their own codes
            except Exception:
                f = ImageFont.load_default(size_px)
            f = (f, fake_bold)
            self._cache[key] = f
        return f


FONTS = _Fonts()

# Wingdings / Symbol bullet characters → the Unicode symbol they show
_WINGDINGS = {"§": "▪", "Ø": "➢", "ü": "✓", "v": "❖", "Ÿ": "•", "l": "●", "n": "■", "q": "❑", "ð": "⇨",
              "è": "➔", "à": "⇒", "Ø": "➢", "": "•", "o": "○", "": "●", "": "▪", "": "➢"}
_SYMBOL_FONT = ["segoe ui symbol", "dejavu sans", "arial unicode ms", "arial"]


# ══════════════════════════════════════════════════════════════════════
#   colours
# ══════════════════════════════════════════════════════════════════════
_PRESET = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 128, 0),
           "blue": (0, 0, 255), "yellow": (255, 255, 0), "gray": (128, 128, 128), "grey": (128, 128, 128),
           "orange": (255, 165, 0), "purple": (128, 0, 128), "darkBlue": (0, 0, 139), "darkRed": (139, 0, 0),
           "darkGreen": (0, 100, 0), "lightGray": (211, 211, 211), "navy": (0, 0, 128), "silver": (192, 192, 192)}
_SYS = {"window": (255, 255, 255), "windowText": (0, 0, 0), "btnFace": (240, 240, 240)}


def _hex(v):
    try:
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (0, 0, 0)


class _Theme:
    def __init__(self, master):
        from lxml import etree
        self.colors = {"dk1": (0, 0, 0), "lt1": (255, 255, 255), "dk2": (68, 84, 106), "lt2": (231, 230, 230),
                       "accent1": (68, 114, 196), "accent2": (237, 125, 49), "accent3": (165, 165, 165),
                       "accent4": (255, 192, 0), "accent5": (91, 155, 213), "accent6": (112, 173, 71),
                       "hlink": (5, 99, 193), "folHlink": (149, 79, 114)}
        self.major, self.minor = "Calibri Light", "Calibri"
        self.fills, self.lines, self.bgfills = [], [], []
        self.part = None                     # theme fills (textures) point at images through the theme's own links
        try:
            self.part = master.part.part_related_by(RT_THEME)
            theme = etree.fromstring(self.part.blob)
            elems = _path(theme, "themeElements")
            for c in (_kid(elems, "clrScheme") if _kid(elems, "clrScheme") is not None else []):
                v = _kid(c, "srgbClr")
                s = _kid(c, "sysClr")
                if v is not None:
                    self.colors[_local(c)] = _hex(v.get("val", "000000"))
                elif s is not None:
                    self.colors[_local(c)] = _hex(s.get("lastClr", "000000"))
            fs = _kid(elems, "fontScheme")
            mj = _path(fs, "majorFont", "latin")
            mn = _path(fs, "minorFont", "latin")
            if mj is not None and mj.get("typeface"):
                self.major = mj.get("typeface")
            if mn is not None and mn.get("typeface"):
                self.minor = mn.get("typeface")
            fmt = _kid(elems, "fmtScheme")
            listed = lambda n: list(_kid(fmt, n)) if _kid(fmt, n) is not None else []  # noqa: E731
            self.fills, self.lines, self.bgfills = listed("fillStyleLst"), listed("lnStyleLst"), listed("bgFillStyleLst")
        except Exception:
            pass
        cmap = master._element.find(_p("clrMap"))
        self.map = dict(cmap.attrib) if cmap is not None else {}


def _mods(rgb, el, alpha=255):
    r, g, b = [c / 255.0 for c in rgb]
    a = alpha / 255.0
    for m in el:
        n = _local(m)
        v = _int(m.get("val"), 100000) / 100000.0
        if n in ("tint", "shade"):
            # Office mixes tints and shades in linear light, not in screen (sRGB) values
            lin = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in (r, g, b)]
            lin = [c * v + (1 - v) for c in lin] if n == "tint" else [c * v for c in lin]
            r, g, b = [1.055 * c ** (1 / 2.4) - 0.055 if c > 0.0031308 else c * 12.92 for c in lin]
        elif n in ("lumMod", "lumOff", "satMod"):
            h, l, s = colorsys.rgb_to_hls(r, g, b)
            if n == "lumMod":
                l *= v
            elif n == "lumOff":
                l += v
            else:
                s *= v
            r, g, b = colorsys.hls_to_rgb(h, min(1, max(0, l)), min(1, max(0, s)))
        elif n == "alpha":
            a = v
        elif n == "alphaMod":
            a *= v
    return tuple(int(round(min(1, max(0, c)) * 255)) for c in (r, g, b)) + (int(round(min(1, max(0, a)) * 255)),)


def color(el, theme, ph=None):
    """An <a:srgbClr>, <a:schemeClr>… element (or a parent holding one) → (r, g, b, a)."""
    if el is None:
        return None
    if _local(el) not in ("srgbClr", "schemeClr", "sysClr", "prstClr", "scrgbClr", "hslClr"):
        for c in el:
            if _local(c) in ("srgbClr", "schemeClr", "sysClr", "prstClr", "scrgbClr", "hslClr"):
                el = c
                break
        else:
            return None
    n = _local(el)
    if n == "srgbClr":
        base = _hex(el.get("val", "000000"))
    elif n == "schemeClr":
        v = el.get("val", "tx1")
        if v == "phClr":
            base = (ph or (0, 0, 0, 255))[:3]
        else:
            v = theme.map.get(v, {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}.get(v, v))
            base = theme.colors.get(v, (0, 0, 0))
    elif n == "sysClr":
        base = _hex(el.get("lastClr")) if el.get("lastClr") else _SYS.get(el.get("val"), (0, 0, 0))
    elif n == "prstClr":
        base = _PRESET.get(el.get("val"), (0, 0, 0))
    elif n == "scrgbClr":
        base = tuple(int(min(1, max(0, _int(el.get(k)) / 100000.0)) * 255) for k in ("r", "g", "b"))
    else:
        base = tuple(int(c * 255) for c in colorsys.hls_to_rgb(_int(el.get("hue")) / 21600000.0,
                                                                _int(el.get("lum")) / 100000.0,
                                                                _int(el.get("sat")) / 100000.0))
    return _mods(base, el)


def fill_of(holder, theme, part, ph=None):
    """The fill inside a spPr / bgPr / tcPr: ('none'), ('solid', rgba), ('grad', stops, angle),
    ('blip', image) — or None when the element says nothing about fill."""
    if holder is None:
        return None
    for c in holder:
        n = _local(c)
        if n == "noFill":
            return ("none",)
        if n == "solidFill":
            col = color(c, theme, ph)
            return ("solid", col) if col else None
        if n == "gradFill":
            stops = []
            for gs in _kids(_kid(c, "gsLst"), "gs"):
                col = color(gs, theme, ph)
                if col:
                    stops.append((_int(gs.get("pos")) / 100000.0, col))
            lin = _kid(c, "lin")
            ang = _int(lin.get("ang")) / 60000.0 if lin is not None else 90.0
            radial = _kid(c, "path") is not None
            return ("grad", sorted(stops), ang, radial) if stops else None
        if n == "blipFill":
            img = _blip_image(c, part)
            if img is None:
                return None
            tile = _kid(c, "tile")
            if tile is not None:            # a texture: repeated at its own size, not stretched
                return ("tile", img, _int(tile.get("sx"), 100000) / 100000.0, _int(tile.get("sy"), 100000) / 100000.0)
            return ("blip", img)
        if n == "pattFill":
            col = color(_kid(c, "fgClr"), theme, ph)
            return ("solid", col) if col else None
        if n == "grpFill":
            return ("none",)
    return None


def _blip_image(blipfill, part):
    blip = _kid(blipfill, "blip")
    if blip is None or part is None:
        return None
    rid = blip.get("{%s}embed" % R)
    if not rid:
        return None
    try:
        data = part.related_part(rid).blob
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    src = _kid(blipfill, "srcRect")
    if src is not None and img.width and img.height:
        l, t, r, b = (_int(src.get(k)) / 100000.0 for k in ("l", "t", "r", "b"))
        box = (int(img.width * l), int(img.height * t), int(img.width * (1 - r)), int(img.height * (1 - b)))
        if box[2] > box[0] and box[3] > box[1]:
            img = img.crop(box)
    for m in blip:
        if _local(m) == "alphaModFix":
            amt = _int(m.get("amt"), 100000) / 100000.0
            img = img.convert("RGBA")
            img.putalpha(img.getchannel("A").point(lambda v: int(v * amt)))
    return img.convert("RGBA")


# ══════════════════════════════════════════════════════════════════════
#   text styles (PowerPoint's inheritance chain)
# ══════════════════════════════════════════════════════════════════════
_MASTER_TYPE = {"ctrTitle": "title", "title": "title", "subTitle": "body", "body": "body", "obj": "body",
                "tbl": "body", "chart": "body", "pic": "body", "dgm": "body", "clipArt": "body", "media": "body",
                "dt": "dt", "ftr": "ftr", "sldNum": "sldNum", "hdr": "hdr"}


def _ph(el):
    for nv in ("nvSpPr", "nvPicPr", "nvGraphicFramePr", "nvCxnSpPr", "nvGrpSpPr"):
        pr = _path(el, nv, "nvPr")
        if pr is not None:
            ph = _kid(pr, "ph")
            if ph is not None:
                return ph.get("type", "obj"), ph.get("idx")
            return None
    return None


def _find_ph(container_el, ptype, idx, by_type_only=False):
    """The placeholder on a layout/master that a slide's placeholder takes after."""
    tree = _path(container_el, "cSld", "spTree")
    if tree is None:
        return None
    cands = []
    for sp in tree.iter():
        if _local(sp) not in ("sp", "pic", "graphicFrame"):
            continue
        info = _ph(sp)
        if info:
            cands.append((sp, info))
    if not by_type_only and idx not in (None, "0"):
        for sp, (t, i) in cands:
            if i == idx:
                return sp
    want = _MASTER_TYPE.get(ptype, "body") if by_type_only else ptype
    for sp, (t, i) in cands:
        if (_MASTER_TYPE.get(t, "body") if by_type_only else t) == want:
            return sp
    if not by_type_only:
        for sp, (t, i) in cands:
            if _MASTER_TYPE.get(t, "body") == _MASTER_TYPE.get(ptype, "body"):
                return sp
    return None


class _Ctx:
    """One slide being drawn."""

    def __init__(self, prs, slide, index):
        self.prs, self.slide, self.index = prs, slide, index
        self.layout = slide.slide_layout
        self.master = self.layout.slide_master
        self.theme = _Theme(self.master)
        self.sw = int(prs.slide_width or 12192000)
        self.sh = int(prs.slide_height or 6858000)
        self.scale = OUT_WIDTH * SS / self.sw
        self.W = int(round(self.sw * self.scale))
        self.H = int(round(self.sh * self.scale))
        self.img = Image.new("RGBA", (self.W, self.H), (255, 255, 255, 255))
        self.draw = ImageDraw.Draw(self.img)
        self.words = []
        tx = self.master._element.find(_p("txStyles"))
        self.txstyles = {k: (tx.find(_p(k)) if tx is not None else None) for k in ("titleStyle", "bodyStyle", "otherStyle")}
        self.default_style = prs.part._element.find(_p("defaultTextStyle"))

    def px(self, emu):
        return emu * self.scale


def _lvl_pr(lst, lvl):
    """lvlNpPr of a list style (lstStyle / txStyles entry) for paragraph level lvl (0-based)."""
    if lst is None:
        return None
    return _kid(lst, "lvl%dpPr" % (lvl + 1))


class _ParaStyle:
    """Merged paragraph + run defaults for one paragraph, most specific source first."""

    def __init__(self, sources):
        self.sources = [s for s in sources if s is not None]

    def attr(self, name, default=None):
        for s in self.sources:
            if s.get(name) is not None:
                return s.get(name)
        return default

    def child(self, name):
        for s in self.sources:
            c = _kid(s, name)
            if c is not None:
                return c
        return None

    def bullet(self):
        """('none') / ('char', char, font, el) / ('num', type, start); plus bullet colour / size sources."""
        for s in self.sources:
            for c in s:
                n = _local(c)
                if n == "buNone":
                    return ("none",)
                if n == "buChar":
                    fnt = _kid(s, "buFont")
                    return ("char", c.get("char", "•"), fnt.get("typeface") if fnt is not None else None)
                if n == "buAutoNum":
                    return ("num", c.get("type", "arabicPeriod"), _int(c.get("startAt"), 1))
                if n == "buBlip":
                    return ("char", "•", None)
        return ("none",)

    def defrpr(self):
        return [_kid(s, "defRPr") for s in self.sources if _kid(s, "defRPr") is not None]


# ══════════════════════════════════════════════════════════════════════
#   geometry
# ══════════════════════════════════════════════════════════════════════
def _xfrm(el):
    """(x, y, w, h, rot°, flipH, flipV) from an element's spPr/xfrm (or p:xfrm on a graphic frame)."""
    x = None
    for cand in (_kid(_kid(el, "spPr"), "xfrm"), _kid(_kid(el, "grpSpPr"), "xfrm"), _kid(el, "xfrm")):
        if cand is not None:
            x = cand
            break
    if x is None:
        return None
    off, ext = _kid(x, "off"), _kid(x, "ext")
    if off is None or ext is None:
        return None
    return [_int(off.get("x")), _int(off.get("y")), _int(ext.get("cx")), _int(ext.get("cy")),
            _int(x.get("rot")) / 60000.0, x.get("flipH") == "1", x.get("flipV") == "1"]


def _polygon(prst, w, h, adj):
    """Points for a preset shape in a w×h box (None = draw it as a rectangle / handled elsewhere)."""
    a = adj
    if prst in ("triangle", "flowChartExtract"):
        return [(w * a.get("adj", 0.5), 0), (w, h), (0, h)]
    if prst == "rtTriangle":
        return [(0, 0), (w, h), (0, h)]
    if prst in ("diamond", "flowChartDecision"):
        return [(w / 2, 0), (w, h / 2), (w / 2, h), (0, h / 2)]
    if prst in ("parallelogram", "flowChartInputOutput"):
        o = min(w, h) * a.get("adj", 0.25)
        return [(o, 0), (w, 0), (w - o, h), (0, h)]
    if prst == "trapezoid":
        o = min(w, h) * a.get("adj", 0.25)
        return [(o, 0), (w - o, 0), (w, h), (0, h)]
    if prst == "hexagon":
        o = min(w, h) * a.get("adj", 0.25)
        return [(o, 0), (w - o, 0), (w, h / 2), (w - o, h), (o, h), (0, h / 2)]
    if prst == "octagon":
        o = min(w, h) * a.get("adj", 0.29289)
        return [(o, 0), (w - o, 0), (w, o), (w, h - o), (w - o, h), (o, h), (0, h - o), (0, o)]
    if prst == "pentagon":
        return [(w / 2, 0), (w, h * 0.38), (w * 0.81, h), (w * 0.19, h), (0, h * 0.38)]
    if prst in ("homePlate", "flowChartOffpageConnector"):
        o = min(w, h) * a.get("adj", 0.5)
        return [(0, 0), (w - o, 0), (w, h / 2), (w - o, h), (0, h)]
    if prst == "chevron":
        o = min(w, h) * a.get("adj", 0.5)
        return [(0, 0), (w - o, 0), (w, h / 2), (w - o, h), (0, h), (o, h / 2)]
    if prst in ("rightArrow", "leftArrow", "upArrow", "downArrow"):
        th, hd = a.get("adj1", 0.5), min(w, h) * a.get("adj2", 0.5)
        if prst in ("rightArrow", "leftArrow"):
            t0, t1 = h * (1 - th) / 2, h * (1 + th) / 2
            pts = [(0, t0), (w - hd, t0), (w - hd, 0), (w, h / 2), (w - hd, h), (w - hd, t1), (0, t1)]
            return [(w - x, y) for x, y in pts] if prst == "leftArrow" else pts
        t0, t1 = w * (1 - th) / 2, w * (1 + th) / 2
        pts = [(t0, h), (t0, hd), (0, hd), (w / 2, 0), (w, hd), (t1, hd), (t1, h)]
        return [(x, h - y) for x, y in pts] if prst == "downArrow" else pts
    if prst in ("star5", "star4", "star6", "star8", "star10", "star12"):
        n = int(prst[4:])
        inner = 0.38 if n == 5 else 0.5
        pts = []
        for i in range(n * 2):
            ang = math.pi * i / n - math.pi / 2
            r = 0.5 if i % 2 == 0 else 0.5 * inner
            pts.append((w / 2 + math.cos(ang) * r * w, h / 2 + math.sin(ang) * r * h))
        return pts
    if prst in ("plus", "mathPlus", "cross"):
        o = min(w, h) * a.get("adj", 0.25)
        return [(o, 0), (w - o, 0), (w - o, o), (w, o), (w, h - o), (w - o, h - o), (w - o, h), (o, h),
                (o, h - o), (0, h - o), (0, o), (o, o)]
    if prst in ("snip1Rect", "snip2SameRect", "snipRoundRect"):
        o = min(w, h) * a.get("adj", a.get("adj1", 0.16667))
        if prst == "snip2SameRect":
            return [(o, 0), (w - o, 0), (w, o), (w, h), (0, h), (0, o)]
        return [(0, 0), (w - o, 0), (w, o), (w, h), (0, h)]
    if prst == "flowChartManualInput":
        return [(0, h * 0.2), (w, 0), (w, h), (0, h)]
    if prst == "flowChartDocument":
        return [(0, 0), (w, 0), (w, h * 0.83), (w * 0.5, h * 0.9), (0, h)]
    return None


def _adj(sp):
    out = {}
    av = _path(sp, "spPr", "prstGeom", "avLst")
    for gd in _kids(av, "gd"):
        m = re.match(r"val\s+(-?\d+)", gd.get("fmla", ""))
        if m:
            out[gd.get("name")] = int(m.group(1)) / 100000.0
    return out


def _cust_paths(sp, w_emu, h_emu):
    """A freeform (custGeom) shape's paths as point lists in 0..1 of the shape box:
    [(polys, filled, stroked)] — curves and arcs sampled into short straight segments."""
    cg = _path(sp, "spPr", "custGeom")
    out = []
    for pth in _kids(_kid(cg, "pathLst"), "path"):
        pw = _int(pth.get("w")) or w_emu or 1
        ph = _int(pth.get("h")) or h_emu or 1
        polys, cur, pos = [], [], (0.0, 0.0)

        def pts_of(cmd):
            return [(_int(pt.get("x")) / pw, _int(pt.get("y")) / ph) for pt in _kids(cmd, "pt")]
        for cmd in pth:
            n = _local(cmd)
            p = pts_of(cmd)
            if n == "moveTo" and p:
                if len(cur) > 1:
                    polys.append(cur)
                cur, pos = [p[0]], p[0]
            elif n == "lnTo" and p:
                cur.append(p[0])
                pos = p[0]
            elif n == "cubicBezTo" and len(p) == 3:
                (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pos, p[0], p[1], p[2]
                for i in range(1, 13):
                    t = i / 12.0
                    u = 1 - t
                    cur.append((u ** 3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * x3,
                                u ** 3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y3))
                pos = p[2]
            elif n == "quadBezTo" and len(p) == 2:
                (x0, y0), (x1, y1), (x2, y2) = pos, p[0], p[1]
                for i in range(1, 11):
                    t = i / 10.0
                    u = 1 - t
                    cur.append((u * u * x0 + 2 * u * t * x1 + t * t * x2, u * u * y0 + 2 * u * t * y1 + t * t * y2))
                pos = p[1]
            elif n == "arcTo":
                wr, hr = _int(cmd.get("wR")) / pw, _int(cmd.get("hR")) / ph
                st = math.radians(_int(cmd.get("stAng")) / 60000.0)
                sw = math.radians(_int(cmd.get("swAng")) / 60000.0)
                cx, cy = pos[0] - wr * math.cos(st), pos[1] - hr * math.sin(st)
                steps = max(4, int(abs(sw) / (math.pi / 24)))
                for i in range(1, steps + 1):
                    a_ = st + sw * i / steps
                    cur.append((cx + wr * math.cos(a_), cy + hr * math.sin(a_)))
                pos = cur[-1] if cur else pos
            elif n == "close":
                if len(cur) > 1:
                    polys.append(cur)
                cur = []
        if len(cur) > 1:
            polys.append(cur)
        out.append((polys, pth.get("fill", "norm") != "none", pth.get("stroke", "1") not in ("0", "false")))
    return out


def _geo_of(ctx, sp, xf):
    """How to draw a shape's outline: ('prst', name, adjustments) or ('cust', paths)."""
    sppr = _kid(sp, "spPr")
    if _kid(sppr, "custGeom") is not None:
        paths = _cust_paths(sp, xf[2], xf[3])
        if paths:
            return ("cust", paths)
    g = _kid(sppr, "prstGeom")
    return ("prst", g.get("prst", "rect") if g is not None else "rect", _adj(sp))


def _mask(geo, w, h):
    """An 'L' mask of the shape in a w×h box, for fills."""
    m = Image.new("L", (max(1, int(w)), max(1, int(h))), 0)
    if geo[0] != "cust":
        _outline(ImageDraw.Draw(m), geo, 0, 0, w, h, fill=255)
        return m
    # a freeform path's sub-paths fill even-odd, as in PowerPoint: an inner outline is a hole
    # (rings, frames, interlocking patterns), and separate paths add up
    from PIL import ImageChops
    w1, h1 = max(1, w - 1), max(1, h - 1)
    for polys, filled, _stroked in geo[1]:
        if not filled:
            continue
        pm = Image.new("L", m.size, 0)
        for poly in polys:
            pts = [(px * w1, py * h1) for px, py in poly]
            if len(pts) < 3:
                continue
            x0, y0 = max(0, int(min(p[0] for p in pts))), max(0, int(min(p[1] for p in pts)))
            x1, y1 = min(m.size[0], int(max(p[0] for p in pts)) + 2), min(m.size[1], int(max(p[1] for p in pts)) + 2)
            if x1 <= x0 or y1 <= y0:
                continue
            tmp = Image.new("L", (x1 - x0, y1 - y0), 0)
            ImageDraw.Draw(tmp).polygon([(px - x0, py - y0) for px, py in pts], fill=255)
            box = (x0, y0, x1, y1)
            pm.paste(ImageChops.difference(pm.crop(box), tmp), box)       # XOR
        m = ImageChops.lighter(m, pm)
    return m


def _outline(d, geo, ox, oy, w, h, fill=None, line=None, width=0):
    """Fill and/or stroke a shape whose box starts at (ox, oy)."""
    w1, h1 = max(1, w - 1), max(1, h - 1)
    if geo[0] == "cust":
        for polys, filled, stroked in geo[1]:
            for poly in polys:
                pts = [(ox + px * w1, oy + py * h1) for px, py in poly]
                if len(pts) < 2:
                    continue
                if fill is not None and filled and len(pts) > 2:
                    d.polygon(pts, fill=fill)
                if line is not None and width and stroked:
                    d.line(pts, fill=line, width=int(width), joint="curve")
        return
    _, prst, adj = geo
    box = (ox, oy, ox + w1, oy + h1)
    if prst in ("ellipse", "flowChartConnector", "donut", "pie", "chord", "flowChartOr", "flowChartSummingJunction"):
        d.ellipse(box, fill=fill, outline=line, width=int(width))
        return
    if prst in ("roundRect", "round2SameRect", "round1Rect", "flowChartAlternateProcess", "flowChartTerminator",
                "wedgeRoundRectCallout", "plaque"):
        r = min(w, h) * adj.get("adj", adj.get("adj1", 0.5 if prst == "flowChartTerminator" else 0.16667))
        d.rounded_rectangle(box, radius=max(0, r), fill=fill, outline=line, width=int(width))
        return
    pts = _polygon(prst, w1, h1, adj)
    if pts:
        pts = [(ox + px, oy + py) for px, py in pts]
        if fill is not None:
            d.polygon(pts, fill=fill)
        if line is not None and width:
            d.line(pts + [pts[0]], fill=line, width=int(width), joint="curve")
        return
    d.rectangle(box, fill=fill, outline=line, width=int(width))


def _paint(ctx, layer, fill, geo, w, h):
    """Put a fill onto a layer (RGBA, w×h) clipped to the shape."""
    if not fill or fill[0] == "none" or w < 1 or h < 1:
        return
    from PIL import ImageChops
    m = _mask(geo, w, h)
    if fill[0] == "solid":
        col = Image.new("RGBA", m.size, fill[1])
    elif fill[0] == "grad":
        col = _gradient(m.size, fill[1], fill[2], fill[3])
    elif fill[0] == "tile":
        img, sx, sy = fill[1], fill[2], fill[3]
        tw = max(1, int(img.width * 9525 * ctx.scale * sx))      # image pixels are 1/96 inch
        th = max(1, int(img.height * 9525 * ctx.scale * sy))
        tile = img.resize((tw, th), Image.LANCZOS)
        col = Image.new("RGBA", m.size, (0, 0, 0, 0))
        for ty in range(0, m.size[1], th):
            for tx in range(0, m.size[0], tw):
                col.paste(tile, (tx, ty))
    else:
        col = fill[1].resize(m.size, Image.LANCZOS)
    col.putalpha(ImageChops.multiply(col.getchannel("A"), m))
    layer.alpha_composite(col)


def _gradient(size, stops, angle, radial):
    import numpy as np
    w, h = size
    if radial:
        yy, xx = np.mgrid[0:h, 0:w]
        t = np.sqrt(((xx - w / 2) / (w / 2 or 1)) ** 2 + ((yy - h / 2) / (h / 2 or 1)) ** 2) / math.sqrt(2)
    else:
        rad = math.radians(angle)
        yy, xx = np.mgrid[0:h, 0:w]
        dx, dy = math.cos(rad), math.sin(rad)
        proj = (xx - w / 2) * dx + (yy - h / 2) * dy
        span = abs(w / 2 * dx) + abs(h / 2 * dy) or 1
        t = (proj / span + 1) / 2
    t = np.clip(t, 0, 1)
    pos = [s[0] for s in stops]
    out = np.zeros((h, w, 4), dtype=np.float32)
    for ch in range(4):
        vals = [s[1][ch] for s in stops]
        out[..., ch] = np.interp(t, pos, vals)
    return Image.fromarray(out.astype("uint8"), "RGBA")


# ══════════════════════════════════════════════════════════════════════
#   text
# ══════════════════════════════════════════════════════════════════════
def _roman(n):
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
            (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def _autonum(kind, n):
    m = re.match(r"(arabic|alphaLc|alphaUc|romanLc|romanUc|circleNumDbPlain|circleNumWdBlackPlain)(.*)", kind)
    base, suffix = (m.group(1), m.group(2)) if m else ("arabic", "Period")
    if base == "alphaLc":
        s = "abcdefghijklmnopqrstuvwxyz"[(n - 1) % 26]
    elif base == "alphaUc":
        s = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[(n - 1) % 26]
    elif base == "romanLc":
        s = _roman(n)
    elif base == "romanUc":
        s = _roman(n).upper()
    else:
        s = str(n)
    return {"Period": s + ".", "ParenR": s + ")", "ParenBoth": "(" + s + ")", "Plain": s,
            "Minus": "- " + s}.get(suffix, s + ".")


class _Run:
    __slots__ = ("text", "font", "fake_bold", "color", "size", "underline", "strike", "rise", "family", "bold", "italic")


def _run_style(ctx, rpr_sources, para_defaults, font_color, scale):
    """Resolve a run's look from its rPr and the inherited defRPr chain."""
    srcs = [s for s in rpr_sources if s is not None] + para_defaults
    get = lambda k, d=None: next((s.get(k) for s in srcs if s.get(k) is not None), d)  # noqa: E731
    sz = _int(get("sz"), 1800) / 100.0 * scale
    bold = get("b") in ("1", "true")
    italic = get("i") in ("1", "true")
    col = None
    for s in srcs:
        c = _kid(s, "solidFill")
        if c is not None:
            col = color(c, ctx.theme)
            break
        if _kid(s, "noFill") is not None:
            col = (0, 0, 0, 0)
            break
    hl = bool(rpr_sources) and rpr_sources[0] is not None and _kid(rpr_sources[0], "hlinkClick") is not None
    if col is None:
        col = ctx.theme.colors["hlink"] + (255,) if hl else font_color
    if col is None:
        col = color_scheme(ctx, "tx1")
    typeface = None
    for s in srcs:
        lat = _kid(s, "latin")
        if lat is not None and lat.get("typeface"):
            typeface = lat.get("typeface")
            break
    typeface = typeface or "+mn-lt"
    if typeface.startswith("+mj"):
        typeface = ctx.theme.major
    elif typeface.startswith("+mn"):
        typeface = ctx.theme.minor
    base = _int(get("baseline"), 0)
    u = get("u")
    return {"size": sz, "bold": bold, "italic": italic, "color": col, "family": typeface,
            "spc": _int(get("spc"), 0) / 100.0 * scale,          # letter spacing, pt
            "underline": bool(u and u != "none") or hl, "strike": get("strike") not in (None, "noStrike"),
            "baseline": base, "caps": get("cap") == "all"}


def _is_symbol(fam):
    return bool(fam) and fam.lower() in ("wingdings", "wingdings 2", "wingdings 3", "symbol", "webdings") and FONTS.has(fam)


def color_scheme(ctx, name):
    v = ctx.theme.map.get(name, {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}.get(name, name))
    return ctx.theme.colors.get(v, (0, 0, 0)) + (255,)


def _layout_text(ctx, txbody, box, chain, font_color=None, kind="other", record=True, fit_scale=None):
    """Lay out and (if ctx.draw) draw a text body in box=(x, y, w, h) canvas px.

    chain: list of (lstStyle element) from most specific (the shape's own) to the master's txStyles.
    Returns the height the text needs."""
    x0, y0, bw, bh = box
    body = _kid(txbody, "bodyPr")
    bprs = [body] + chain.get("bodyPr", [])

    def battr(k, d=None):
        for b in bprs:
            if b is not None and b.get(k) is not None:
                return b.get(k)
        return d
    first_last = battr("spcFirstLastPara") in ("1", "true")
    lins = ctx.px(_int(battr("lIns"), 91440))
    rins = ctx.px(_int(battr("rIns"), 91440))
    tins = ctx.px(_int(battr("tIns"), 45720))
    bins = ctx.px(_int(battr("bIns"), 45720))
    anchor = battr("anchor", "t")
    wrap = battr("wrap", "square") != "none"
    scale, spc_red = 1.0, 0.0
    autofit = None
    for b in bprs:
        if b is None:
            continue
        for c in b:
            if _local(c) in ("normAutofit", "spAutoFit", "noAutofit"):
                autofit = c
                break
        if autofit is not None:
            break
    if autofit is not None and _local(autofit) == "normAutofit":
        scale = _int(autofit.get("fontScale"), 100000) / 100000.0
        spc_red = _int(autofit.get("lnSpcReduction"), 0) / 100000.0
    if fit_scale is not None:
        scale = fit_scale
    avail = max(1.0, bw - lins - rins)

    lines = []          # each: dict(top_gap, height, ascent, items=[(x, word, style)], x_start, width, align)
    counters = {}
    paras = _kids(txbody, "p")
    y = 0.0
    first_para = True
    for p in paras:
        ppr = _kid(p, "pPr")
        lvl = _int(ppr.get("lvl"), 0) if ppr is not None else 0
        sources = [ppr] + [_lvl_pr(lst, lvl) for lst in chain.get("lst", [])]
        ps = _ParaStyle(sources)
        algn = ps.attr("algn", "l")
        marl = ctx.px(_int(ps.attr("marL"), 0))
        indent = ctx.px(_int(ps.attr("indent"), 0))
        defaults = ps.defrpr()
        # runs
        runs = []
        for c in p:
            n = _local(c)
            if n in ("r", "fld"):
                t = (_kid(c, "t").text if _kid(c, "t") is not None else "") or ""
                if n == "fld" and (c.get("type") or "").startswith("slidenum"):
                    t = str(ctx.index + 1)
                elif n == "fld" and (c.get("type") or "").startswith("datetime"):
                    import datetime                 # an updating date shows today, as in PowerPoint
                    d_ = datetime.date.today()
                    t = f"{d_.month}/{d_.day}/{d_.year}"
                st = _run_style(ctx, [_kid(c, "rPr")], defaults, font_color, scale)
                runs.append((t.replace("\t", "    ").replace("\u000b", "\n"), st))
            elif n == "br":
                runs.append(("\n", _run_style(ctx, [_kid(c, "rPr")], defaults, font_color, scale)))
        end_st = _run_style(ctx, [_kid(p, "endParaRPr")], defaults, font_color, scale)
        has_text = any(t.strip() for t, _ in runs)
        first_st = next((st for t, st in runs if t.strip()), end_st)
        # spacing
        def spacing(name):
            el = ps.child(name)
            if el is None:
                return None
            pts = _kid(el, "spcPts")
            pct = _kid(el, "spcPct")
            if pts is not None:
                return ("pts", _int(pts.get("val")) / 100.0)
            if pct is not None:
                return ("pct", _int(pct.get("val")) / 100000.0)
            return None
        ln = spacing("lnSpc") or ("pct", 1.0)
        bef = spacing("spcBef")
        aft = spacing("spcAft")
        size_px = first_st["size"] * ctx.scale * EMU_PER_PT
        if bef and (not first_para or first_last):
            y += bef[1] * ctx.scale * EMU_PER_PT * scale if bef[0] == "pts" else bef[1] * size_px * 1.2
        first_para = False
        # bullet
        bullet = None
        bu = ps.bullet() if has_text else ("none",)
        for k in [k for k in counters if k > lvl]:
            counters.pop(k)
        if bu[0] == "num":
            counters[lvl] = counters.get(lvl, bu[2] - 1) + 1
            bullet = (_autonum(bu[1], counters[lvl]), None)
        else:
            counters.pop(lvl, None)
            if bu[0] == "char":
                ch, fam = bu[1], bu[2]
                if fam and fam.lower() in ("wingdings", "wingdings 2", "wingdings 3", "symbol", "webdings"):
                    if FONTS.has(fam):           # draw the real symbol (symbol fonts keep them at U+F0xx)
                        ch = ch if ord(ch) >= 0xF000 else chr(0xF000 + ord(ch))
                    else:                        # not installed: the Unicode look-alike
                        plain = chr(ord(ch) - 0xF000) if ord(ch) >= 0xF000 else ch
                        ch, fam = _WINGDINGS.get(plain, "▸"), "segoe ui symbol"
                bullet = (ch, fam)
        bu_size = first_st["size"]
        szp = ps.child("buSzPct")
        if szp is not None:
            bu_size = first_st["size"] * _int(szp.get("val"), 100000) / 100000.0
        buclr = ps.child("buClr")
        bu_color = color(buclr, ctx.theme) if buclr is not None else first_st["color"]

        # words → lines
        words = []
        for t, st in runs:
            if st["caps"]:
                t = t.upper()
            for part in re.split(r"(\n| +)", t):
                if part == "":
                    continue
                # a line may also break after a hyphen ("pre-" | "applied"), as in PowerPoint
                for piece in (re.split(r"(?<=[A-Za-z]-)(?=[A-Za-z])", part) if "-" in part else [part]):
                    words.append((piece, st))
        line_items, line_w = [], 0.0
        start_x = marl + (indent if not bullet else 0)
        if bullet:
            # the bullet hangs at marL+indent; the text starts at marL — but never on top of the bullet
            bf0, _ = FONTS.get(bullet[1] or first_st["family"], bu_size * ctx.scale * EMU_PER_PT,
                               symbol=_is_symbol(bullet[1]))
            bullet_end = marl + indent + bf0.getlength(bullet[0])
            start_x = marl if bullet_end <= marl else bullet_end + bf0.size * 0.25
        first_line = True

        def font_for(st):
            sz = st["size"] * ctx.scale * EMU_PER_PT
            if st["baseline"]:
                sz *= 0.7
            return FONTS.get(st["family"], sz, st["bold"], st["italic"])

        def push_line():
            nonlocal line_items, line_w, first_line, start_x
            lines.append({"items": line_items, "width": line_w, "x": start_x, "align": algn,
                          "ln": ln, "first": first_line, "bullet": bullet if first_line else None,
                          "bu_size": bu_size, "bu_color": bu_color, "marl": marl, "indent": indent,
                          "end_st": end_st})
            line_items, line_w = [], 0.0
            first_line = False
            start_x = marl
        for word, st in words:
            if word == "\n":
                push_line()
                continue
            f, _fb = font_for(st)
            wlen = f.getlength(word) + st["spc"] * ctx.scale * EMU_PER_PT * len(word)
            space = word.isspace()
            limit = avail * 0.985 - start_x         # PowerPoint measures text a touch wider: wrap as it does
            if wrap and line_items and not space and line_w + wlen > limit:
                # drop trailing spaces before breaking
                while line_items and line_items[-1][0].isspace():
                    line_w -= line_items.pop()[2]
                push_line()
            if space and not line_items:
                continue
            line_items.append((word, st, wlen))
            line_w += wlen
        push_line()
        # heights of this paragraph's lines (earlier paragraphs' lines already have a y)
        para_lines = [L for L in lines if "y" not in L]
        for L in para_lines:
            asc = desc = 0
            size_max = 0.0
            for word, st, _w in L["items"] or [(" ", L["end_st"], 0)]:
                f, _ = font_for(st)
                a_, d_ = f.getmetrics()
                asc, desc = max(asc, a_), max(desc, d_)
                size_max = max(size_max, st["size"] * ctx.scale * EMU_PER_PT)
            single = 1.2 * size_max                 # PowerPoint's "single" line: 1.2 × the font size
            if L["ln"][0] == "pts":
                lh = L["ln"][1] * ctx.scale * EMU_PER_PT * scale
            else:
                lh = single * max(0.5, L["ln"][1] - spc_red)
            L["y"] = y
            # extra spacing goes above the text; the glyphs sit centred in a single line's height
            L["asc"] = (lh - single) + (single - (asc + desc)) / 2 + asc
            L["h"] = lh
            y += lh
        text_end = y                                  # the space after the last paragraph doesn't count
        if aft:
            y += aft[1] * ctx.scale * EMU_PER_PT * scale if aft[0] == "pts" else aft[1] * size_px * 1.2
    text_h = (y if first_last else text_end) if paras else 0.0
    need = text_h + tins + bins
    # "shrink on overflow" uses the scale PowerPoint saved (fontScale); with none saved it decided
    # no shrinking was needed — re-measuring here shrank titles PowerPoint shows full size

    if not record:
        return need
    if anchor == "ctr":
        top = y0 + tins + (bh - tins - bins - text_h) / 2
    elif anchor == "b":
        top = y0 + bh - bins - text_h
    else:
        top = y0 + tins
    d = ctx.draw
    for L in lines:
        base = top + L["y"] + L["asc"]
        width = L["width"]
        xs = x0 + lins + L["x"]
        if L["align"] == "ctr":
            xs = x0 + lins + L["x"] + (avail - L["x"] - width) / 2
        elif L["align"] == "r":
            xs = x0 + lins + avail - width
        if L["bullet"]:
            ch, fam = L["bullet"]
            st0 = L["items"][0][1] if L["items"] else L["end_st"]
            bf, _ = FONTS.get(fam or st0["family"], L["bu_size"] * ctx.scale * EMU_PER_PT, False, False,
                              symbol=_is_symbol(fam))
            bx = x0 + lins + L["marl"] + L["indent"]
            if L["align"] == "ctr":
                bx = xs - bf.getlength(ch + " ")
            d.text((bx, base), ch, font=bf, fill=tuple(L["bu_color"] or (0, 0, 0, 255)), anchor="ls")
        x = xs
        items = L["items"]
        last_ink = max((i for i, it in enumerate(items) if not it[0].isspace()), default=-1)
        for i, (word, st, wlen) in enumerate(items):
            f, fake_bold = font_for(st)
            yb = base - (st["size"] * ctx.scale * EMU_PER_PT * 0.33 if st["baseline"] > 0 else
                         -st["size"] * ctx.scale * EMU_PER_PT * 0.12 if st["baseline"] < 0 else 0)
            fill = tuple(st["color"])
            if fill[3] > 0:
                spc = st["spc"] * ctx.scale * EMU_PER_PT
                if spc and not word.isspace():             # letter spacing: one character at a time
                    cx_ = x
                    for chr_ in word:
                        d.text((cx_, yb), chr_, font=f, fill=fill, anchor="ls",
                               stroke_width=1 if fake_bold else 0, stroke_fill=fill)
                        cx_ += f.getlength(chr_) + spc
                elif not word.isspace():
                    d.text((x, yb), word, font=f, fill=fill, anchor="ls",
                           stroke_width=1 if fake_bold else 0, stroke_fill=fill)
                # underline runs under the spaces between words too, not past the last word
                if st["underline"] and i <= last_ink:
                    uy = yb + max(1, f.size * 0.1)
                    d.line((x, uy, x + wlen, uy), fill=fill, width=max(1, int(f.size / 14)))
                if st["strike"] and not word.isspace():
                    sy = yb - f.size * 0.3
                    d.line((x, sy, x + wlen, sy), fill=fill, width=max(1, int(f.size / 14)))
            if not word.isspace() and ctx.words is not None:
                asc, desc = f.getmetrics()
                ctx.words.append((x, yb - asc, wlen, asc + desc, word))
            x += wlen
    return need


# ══════════════════════════════════════════════════════════════════════
#   shapes
# ══════════════════════════════════════════════════════════════════════
def _text_chain(ctx, sp, owner):
    """lstStyle + bodyPr sources for a shape's text, most specific first."""
    lst, bpr = [], []
    tx = _kid(sp, "txBody")
    if tx is not None:
        lst.append(_kid(tx, "lstStyle"))
    info = _ph(sp)
    if info and owner == "slide":
        lay = _find_ph(ctx.layout._element, info[0], info[1])
        mas = _find_ph(ctx.master._element, info[0], info[1], by_type_only=True)
        for base in (lay, mas):
            btx = _kid(base, "txBody") if base is not None else None
            if btx is not None:
                lst.append(_kid(btx, "lstStyle"))
                bpr.append(_kid(btx, "bodyPr"))
    elif info and owner == "layout":
        mas = _find_ph(ctx.master._element, info[0], info[1], by_type_only=True)
        btx = _kid(mas, "txBody") if mas is not None else None
        if btx is not None:
            lst.append(_kid(btx, "lstStyle"))
            bpr.append(_kid(btx, "bodyPr"))
    if info:
        t = _MASTER_TYPE.get(info[0], "body")
        lst.append(ctx.txstyles["titleStyle"] if t == "title" else
                   ctx.txstyles["bodyStyle"] if t == "body" else ctx.txstyles["otherStyle"])
    else:
        lst.append(ctx.default_style)
        lst.append(ctx.txstyles["otherStyle"])
    return {"lst": [l for l in lst if l is not None], "bodyPr": [b for b in bpr if b is not None]}


def _inherited_xfrm(ctx, sp, owner):
    xf = _xfrm(sp)
    if xf is not None:
        return xf
    info = _ph(sp)
    if not info:
        return None
    if owner == "slide":
        for base in (_find_ph(ctx.layout._element, info[0], info[1]),
                     _find_ph(ctx.master._element, info[0], info[1], by_type_only=True)):
            if base is not None and _xfrm(base) is not None:
                return _xfrm(base)
    elif owner == "layout":
        base = _find_ph(ctx.master._element, info[0], info[1], by_type_only=True)
        if base is not None:
            return _xfrm(base)
    return None


def _style_ref(ctx, sp, ref):
    st = _kid(sp, "style")
    r = _kid(st, ref) if st is not None else None
    if r is None:
        return None, None
    return _int(r.get("idx")), color(r, ctx.theme)


class _Group:
    """Coordinate transform for shapes inside groups (child space → slide space)."""

    def __init__(self, parent=None, xf=None, choff=(0, 0), chext=(1, 1)):
        self.parent, self.xf, self.choff, self.chext = parent, xf, choff, chext

    def map(self, x, y, w, h):
        if self.xf is None:
            return x, y, w, h
        gx, gy, gw, gh = self.xf[:4]
        sx = gw / self.chext[0] if self.chext[0] else 1
        sy = gh / self.chext[1] if self.chext[1] else 1
        x, y, w, h = gx + (x - self.choff[0]) * sx, gy + (y - self.choff[1]) * sy, w * sx, h * sy
        return self.parent.map(x, y, w, h) if self.parent else (x, y, w, h)


def _draw_tree(ctx, tree, part, owner, group=None):
    group = group or _Group()
    for el in tree:
        n = _local(el)
        try:
            if n == "AlternateContent":
                choice = _kid(el, "Choice")
                fb = _kid(el, "Fallback")
                for src in (choice, fb):
                    if src is not None and len(src):
                        _draw_tree(ctx, list(src), part, owner, group)
                        break
            elif n in ("sp", "cxnSp"):
                _draw_shape(ctx, el, part, owner, group)
            elif n == "pic":
                _draw_picture(ctx, el, part, owner, group)
            elif n == "grpSp":
                gxf = _xfrm(el)
                gp = _kid(_kid(el, "grpSpPr"), "xfrm")
                choff = _kid(gp, "chOff") if gp is not None else None
                chext = _kid(gp, "chExt") if gp is not None else None
                g = _Group(group, gxf,
                           (_int(choff.get("x")), _int(choff.get("y"))) if choff is not None else (0, 0),
                           (_int(chext.get("cx"), 1), _int(chext.get("cy"), 1)) if chext is not None else (1, 1))
                _draw_tree(ctx, [c for c in el if _local(c) not in ("nvGrpSpPr", "grpSpPr")], part, owner, g)
            elif n == "graphicFrame":
                _draw_frame(ctx, el, part, owner, group)
        except Exception:
            continue            # one odd shape never costs the whole slide


def _hidden(el):
    for nv in ("nvSpPr", "nvPicPr", "nvGraphicFramePr", "nvCxnSpPr", "nvGrpSpPr"):
        c = _path(el, nv, "cNvPr")
        if c is not None:
            return c.get("hidden") in ("1", "true")
    return False


def _box(ctx, xf, group):
    x, y, w, h = group.map(*xf[:4])
    return ctx.px(x), ctx.px(y), ctx.px(w), ctx.px(h)


def _place(ctx, layer, x, y, rot, fh, fv):
    if fh:
        layer = layer.transpose(Image.FLIP_LEFT_RIGHT)
    if fv:
        layer = layer.transpose(Image.FLIP_TOP_BOTTOM)
    if rot:
        cx, cy = x + layer.width / 2, y + layer.height / 2
        layer = layer.rotate(-rot, resample=Image.BICUBIC, expand=True)
        x, y = cx - layer.width / 2, cy - layer.height / 2
    ctx.img.alpha_composite(layer, (int(round(x)), int(round(y))))


def _draw_shape(ctx, sp, part, owner, group):
    if _hidden(sp):
        return
    info = _ph(sp)
    if info and owner != "slide":
        return                  # a layout/master placeholder is a prompt, not content
    xf = _inherited_xfrm(ctx, sp, owner)
    if xf is None:
        return
    x, y, w, h = _box(ctx, xf, group)
    rot, fh, fv = xf[4], xf[5], xf[6]
    sppr = _kid(sp, "spPr")
    geom = _kid(sppr, "prstGeom")
    prst = geom.get("prst", "rect") if geom is not None else ("rect" if _kid(sppr, "custGeom") is None else "rect")
    adj = _adj(sp)
    fill = fill_of(sppr, ctx.theme, part)
    fidx, fcol = _style_ref(ctx, sp, "fillRef")
    if fill is None and fidx and fidx > 0:
        fill = ("solid", fcol) if fcol else None
        if fidx >= 1 and fidx - 1 < len(ctx.theme.fills):
            f2 = fill_of(_wrap(ctx.theme.fills[fidx - 1]), ctx.theme, ctx.theme.part, fcol)
            fill = f2 or fill
    if fill is None and info and owner == "slide":
        for base in (_find_ph(ctx.layout._element, info[0], info[1]),):
            if base is not None:
                fill = fill_of(_kid(base, "spPr"), ctx.theme, ctx.layout.part)
    ln = _kid(sppr, "ln")
    line_col, line_w = None, 0
    lidx, lcol = _style_ref(ctx, sp, "lnRef")
    if ln is not None and _kid(ln, "noFill") is not None:
        line_col = None
    elif ln is not None and _kid(ln, "solidFill") is not None:
        line_col = color(_kid(ln, "solidFill"), ctx.theme)
        line_w = _int(ln.get("w"), 12700)
    elif lidx and lidx > 0 and lcol:
        line_col = lcol
        base_ln = ctx.theme.lines[lidx - 1] if lidx - 1 < len(ctx.theme.lines) else None
        line_w = _int(base_ln.get("w") if base_ln is not None else None, 9525 * lidx)
        if ln is not None and ln.get("w"):
            line_w = _int(ln.get("w"))
    lw = ctx.px(line_w) if line_col else 0
    is_line = prst in ("line", "straightConnector1", "bentConnector2", "bentConnector3", "curvedConnector3") \
        or _local(sp) == "cxnSp"
    if is_line:
        if line_col and line_col[3] > 0:
            x1, y1, x2, y2 = x, y, x + w, y + h
            if fh:
                x1, x2 = x2, x1
            if fv:
                y1, y2 = y2, y1
            if rot:
                cx, cy = x + w / 2, y + h / 2
                r = math.radians(rot)
                pts = []
                for px_, py_ in ((x1, y1), (x2, y2)):
                    dx, dy = px_ - cx, py_ - cy
                    pts.append((cx + dx * math.cos(r) - dy * math.sin(r), cy + dx * math.sin(r) + dy * math.cos(r)))
                (x1, y1), (x2, y2) = pts
            ctx.draw.line((x1, y1, x2, y2), fill=tuple(line_col), width=max(1, int(lw)))
        return
    W, H = max(1, int(round(w))), max(1, int(round(h)))
    geo = _geo_of(ctx, sp, xf)
    has_fill = bool(fill) and fill[0] != "none"
    has_line = bool(line_col) and line_col[3] > 0 and lw > 0
    if has_fill or has_line:
        m = int(math.ceil(lw)) + 2                 # room for an outline centred on the edge
        layer = Image.new("RGBA", (W + 2 * m, H + 2 * m), (0, 0, 0, 0))
        if has_fill:
            inner = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            _paint(ctx, inner, fill, geo, W, H)
            layer.alpha_composite(inner, (m, m))
        if has_line:
            _outline(ImageDraw.Draw(layer), geo, m - lw / 2, m - lw / 2, W + lw, H + lw,
                     line=tuple(line_col), width=max(1, int(round(lw))))
        _place(ctx, layer, x - m, y - m, rot, fh, fv)
    tx = _kid(sp, "txBody")
    if tx is not None and "".join(t.text or "" for t in tx.iter(_a("t"))).strip():
        _, fontcol = _style_ref(ctx, sp, "fontRef")
        chain = _text_chain(ctx, sp, owner)
        txxf = _kid(sp, "txXfrm")              # SmartArt: text sits in its own box
        tbox = (x, y, w, h)
        if txxf is not None:
            off, ext = _kid(txxf, "off"), _kid(txxf, "ext")
            if off is not None and ext is not None:
                tbox = _box(ctx, [_int(off.get("x")), _int(off.get("y")), _int(ext.get("cx")), _int(ext.get("cy"))], group)
        if rot and abs(rot) > 1 and abs(rot - 360) > 1:
            _rotated_text(ctx, tx, tbox, chain, fontcol, rot)
        else:
            _layout_text(ctx, tx, tbox, chain, fontcol)


def _rotated_text(ctx, tx, box, chain, fontcol, rot):
    x, y, w, h = box
    layer = Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0))
    saved = ctx.img, ctx.draw, ctx.words
    ctx.img, ctx.draw, ctx.words = layer, ImageDraw.Draw(layer), None
    try:
        _layout_text(ctx, tx, (0, 0, w, h), chain, fontcol)
    finally:
        ctx.img, ctx.draw, ctx.words = saved
    _place(ctx, layer, x, y, rot, False, False)


def _wrap(fill_el):
    """A theme fill style (e.g. <a:solidFill>) wrapped so fill_of can read it."""
    from lxml import etree
    w = etree.Element(_a("spPr"))
    w.append(_copy(fill_el))
    return w


def _copy(el):
    from copy import deepcopy
    return deepcopy(el)


def _draw_picture(ctx, pic, part, owner, group):
    if _hidden(pic):
        return
    if _ph(pic) and owner != "slide":
        return
    xf = _inherited_xfrm(ctx, pic, owner)
    if xf is None:
        return
    x, y, w, h = _box(ctx, xf, group)
    img = _blip_image(_kid(pic, "blipFill"), part)
    if img is None or w < 1 or h < 1:
        return
    W, H = max(1, int(round(w))), max(1, int(round(h)))
    img = img.resize((W, H), Image.LANCZOS)
    geom = _path(pic, "spPr", "prstGeom")
    prst = geom.get("prst", "rect") if geom is not None else "rect"
    if prst != "rect":
        from PIL import ImageChops
        m = _mask(("prst", prst, _adj(pic)), W, H)
        img.putalpha(ImageChops.multiply(img.getchannel("A"), m))
    ln = _path(pic, "spPr", "ln")
    if ln is not None and _kid(ln, "solidFill") is not None:
        col = color(_kid(ln, "solidFill"), ctx.theme)
        lw = max(1, int(ctx.px(_int(ln.get("w"), 12700))))
        ImageDraw.Draw(img).rectangle((0, 0, W - 1, H - 1), outline=tuple(col), width=lw)
    _place(ctx, img, x, y, xf[4], xf[5], xf[6])


# ── tables, charts, SmartArt ─────────────────────────────────────────
_TABLE_ACCENT = {"{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}": "accent1", "{21E4AEA4-8DFA-4A89-87EB-49C32662AFE8}": "accent2",
                 "{F5AB1C69-6EDB-4FF4-983F-18BD219EF322}": "accent3", "{00A15C55-8517-42AA-B614-E9B94910E393}": "accent4",
                 "{7DF18680-E054-41AD-8BC1-D1AEF772440D}": "accent5", "{93296810-A885-4BE3-A3E7-6D5BEEA58F35}": "accent6",
                 "{073A0DAA-6AF3-43AB-8588-CEC1D06C72B9}": "dk1"}
_NO_STYLE = {"{2D5ABB26-0587-4C30-8999-92F81FD0307C}": False, "{5940675A-B579-460E-94D1-54222C63F5DA}": True}


def _tint(rgb, t):
    return tuple(int(c * t + 255 * (1 - t)) for c in rgb[:3]) + (255,)


def _draw_frame(ctx, fr, part, owner, group):
    if _hidden(fr) or (_ph(fr) and owner != "slide"):
        return
    xf = _xfrm(fr) or _inherited_xfrm(ctx, fr, owner)
    if xf is None:
        return
    x, y, w, h = _box(ctx, xf, group)
    gd = _path(fr, "graphic", "graphicData")
    if gd is None:
        return
    uri = gd.get("uri", "")
    tbl = _kid(gd, "tbl")
    if tbl is not None:
        _draw_table(ctx, tbl, (x, y, w, h), part)
        return
    if uri.endswith("/diagram"):
        if _draw_smartart(ctx, fr, part, xf, group):
            return
    if uri.endswith("/chart"):
        _draw_chart_box(ctx, gd, part, (x, y, w, h))
        return
    # OLE objects and the like: their preview picture
    for pic in gd.iter(_p("pic")):
        img = _blip_image(_kid(pic, "blipFill"), part)
        if img is not None and w >= 1 and h >= 1:
            ctx.img.alpha_composite(img.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS), (int(x), int(y)))
        return


def _table_style_def(ctx, sid):
    """The deck's own definition of a table style (PowerPoint saves every style a deck uses)."""
    from lxml import etree
    cache = getattr(ctx.prs, "_mrsolis_tblstyles", None)
    if cache is None:
        cache = {}
        try:
            for rel in ctx.prs.part.rels.values():
                if rel.reltype.endswith("/tableStyles"):
                    root = etree.fromstring(rel.target_part.blob)
                    for st in root:
                        if _local(st) == "tblStyle" and st.get("styleId"):
                            cache[st.get("styleId")] = st
        except Exception:
            pass
        ctx.prs._mrsolis_tblstyles = cache
    return cache.get(sid)


def _cell_regions(flags, ri, ci, nr, nc):
    """Which parts of a table style apply to a cell, in the order PowerPoint layers them."""
    rs = ["wholeTbl"]
    if flags["bandCol"]:
        k = ci - (1 if flags["firstCol"] else 0)
        if k >= 0 and not (flags["lastCol"] and ci == nc - 1):
            rs.append("band1V" if k % 2 == 0 else "band2V")
    if flags["bandRow"]:
        k = ri - (1 if flags["firstRow"] else 0)
        if k >= 0 and not (flags["lastRow"] and ri == nr - 1):
            rs.append("band1H" if k % 2 == 0 else "band2H")
    if flags["lastCol"] and ci == nc - 1:
        rs.append("lastCol")
    if flags["firstCol"] and ci == 0:
        rs.append("firstCol")
    if flags["lastRow"] and ri == nr - 1:
        rs.append("lastRow")
    if flags["firstRow"] and ri == 0:
        rs.append("firstRow")
    return rs


def _style_cell(ctx, style, regions):
    """Fill, borders (left/right/top/bottom/insideH/insideV) and text look from a table style."""
    fill, borders, txt = None, {}, {}
    for name in regions:
        reg = _kid(style, name)
        if reg is None:
            continue
        tcs = _kid(reg, "tcStyle")
        if tcs is not None:
            f = _kid(tcs, "fill")
            if f is not None:
                fill = fill_of(f, ctx.theme, ctx.theme.part) or fill
            fr = _kid(tcs, "fillRef")
            if fr is not None:
                col = color(fr, ctx.theme)
                fill = ("solid", col) if col else fill
            bdr = _kid(tcs, "tcBdr")
            for side in (bdr if bdr is not None else []):
                ln = _kid(side, "ln")
                if ln is not None:
                    if _kid(ln, "noFill") is not None:
                        borders[_local(side)] = None
                    elif _kid(ln, "solidFill") is not None:
                        borders[_local(side)] = (color(_kid(ln, "solidFill"), ctx.theme), _int(ln.get("w"), 12700))
                lr = _kid(side, "lnRef")
                if lr is not None and color(lr, ctx.theme):
                    borders[_local(side)] = (color(lr, ctx.theme), 12700)
        tx = _kid(reg, "tcTxStyle")
        if tx is not None:
            if tx.get("b") in ("on", "off"):
                txt["b"] = tx.get("b") == "on"
            for c in tx:
                if _local(c) in ("srgbClr", "schemeClr", "prstClr", "sysClr"):
                    txt["color"] = color(c, ctx.theme)
    return fill, borders, txt


def _draw_table(ctx, tbl, box, part):
    x, y, w, h = box
    cols = [ctx.px(_int(gc.get("w"))) for gc in _kids(_kid(tbl, "tblGrid"), "gridCol")]
    rows = _kids(tbl, "tr")
    tpr = _kid(tbl, "tblPr")
    flags = {k: tpr is not None and tpr.get(k) in ("1", "true")
             for k in ("firstRow", "lastRow", "firstCol", "lastCol", "bandRow", "bandCol")}
    sid_el = _kid(tpr, "tableStyleId") if tpr is not None else None
    sid = (sid_el.text or "").strip() if sid_el is not None else "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"
    style = _table_style_def(ctx, sid)
    accent = _TABLE_ACCENT.get(sid, "accent1")
    plain = sid in _NO_STYLE
    acc = color_scheme(ctx, accent) if accent != "dk1" else color_scheme(ctx, "tx1")
    chain_cell = {"lst": [ctx.default_style], "bodyPr": []}
    nr = len(rows)
    nc = len(cols) or max((len(_kids(r, "tc")) for r in rows), default=1)

    def look(ri, ci):
        """(fill, borders, text) for a cell — from the deck's style, else a close built-in look."""
        if style is not None:
            return _style_cell(ctx, style, _cell_regions(flags, ri, ci, nr, nc))
        if plain:
            grid = (0, 0, 0, 255) if _NO_STYLE.get(sid) else None
            b = {k: (grid, 12700) for k in ("left", "right", "top", "bottom", "insideH", "insideV")} if grid else {}
            return None, b, {}
        white = ((255, 255, 255, 255), 12700)
        b = {k: white for k in ("left", "right", "top", "bottom", "insideH", "insideV")}
        if flags["firstRow"] and ri == 0:
            return ("solid", acc), b, {"b": True, "color": color_scheme(ctx, "bg1")}
        k = ri - (1 if flags["firstRow"] else 0)
        return ("solid", _tint(acc, 0.4 if flags["bandRow"] and k % 2 == 0 else 0.2)), b, {}

    def cell_margins(tcpr):
        return {k: ctx.px(_int(tcpr.get(k), d)) if tcpr is not None else ctx.px(d)
                for k, d in (("marL", 91440), ("marR", 91440), ("marT", 45720), ("marB", 45720))}

    def prepare(tx, tcpr, txt):
        """Give the cell's text the table's margins and its style's bold (runs keep their own say)."""
        bpr = _kid(tx, "bodyPr")
        mar = cell_margins(tcpr)
        if bpr is not None:
            for k, v in (("lIns", "marL"), ("rIns", "marR"), ("tIns", "marT"), ("bIns", "marB")):
                bpr.set(k, str(int(mar[v] / ctx.scale)))
            if tcpr is not None and tcpr.get("anchor"):
                bpr.set("anchor", tcpr.get("anchor"))
        if txt.get("b"):
            from lxml import etree
            for r in tx.iter(_a("r")):
                rpr = _kid(r, "rPr")
                if rpr is None:
                    rpr = etree.Element(_a("rPr"))
                    r.insert(0, rpr)
                if rpr.get("b") is None:
                    rpr.set("b", "1")

    # row heights grow to fit their text, as PowerPoint's do
    heights = []
    saved = ctx.words
    for ri, r in enumerate(rows):
        rh = ctx.px(_int(r.get("h")))
        for ci, tc in enumerate(_kids(r, "tc")):
            span = _int(tc.get("gridSpan"), 1)
            cw = sum(cols[ci:ci + span]) if cols else w
            tx = _kid(tc, "txBody")
            if tx is not None and tc.get("hMerge") != "1" and tc.get("vMerge") != "1" and _int(tc.get("rowSpan"), 1) == 1:
                prepare(tx, _kid(tc, "tcPr"), look(ri, ci)[2])
                ctx.words = None
                rh = max(rh, _layout_text(ctx, tx, (0, 0, cw, rh), chain_cell, record=False))
        heights.append(rh)
    ctx.words = saved

    cy = y
    for ri, r in enumerate(rows):
        cx = x
        cells = _kids(r, "tc")
        for ci, tc in enumerate(cells):
            span = _int(tc.get("gridSpan"), 1)
            cw = sum(cols[ci:ci + span]) if cols else w / max(1, len(cells))
            if tc.get("hMerge") == "1":
                cx += cols[ci] if ci < len(cols) else 0
                continue
            ch = sum(heights[ri:ri + _int(tc.get("rowSpan"), 1)])
            tcpr = _kid(tc, "tcPr")
            sfill, sborders, txt = look(ri, ci)
            fill = fill_of(tcpr, ctx.theme, part)
            fill = fill if fill is not None else sfill
            if fill and fill[0] == "solid":
                ctx.draw.rectangle((cx, cy, cx + cw, cy + ch), fill=tuple(fill[1]))
            elif fill and fill[0] in ("grad", "blip", "tile"):
                layer = Image.new("RGBA", (max(1, int(cw)), max(1, int(ch))), (0, 0, 0, 0))
                _paint(ctx, layer, fill, ("prst", "rect", {}), layer.width, layer.height)
                ctx.img.alpha_composite(layer, (int(cx), int(cy)))
            last_col = ci + span >= nc
            last_row = ri + _int(tc.get("rowSpan"), 1) >= nr
            sides = {"lnL": "left" if ci == 0 else "insideV", "lnR": "right" if last_col else "insideV",
                     "lnT": "top" if ri == 0 else "insideH", "lnB": "bottom" if last_row else "insideH"}
            for side, key in sides.items():
                bdr = sborders.get(key)
                ln = _kid(tcpr, side) if tcpr is not None else None
                if ln is not None:                     # the cell's own border wins
                    if _kid(ln, "noFill") is not None:
                        bdr = None
                    elif _kid(ln, "solidFill") is not None:
                        bdr = (color(_kid(ln, "solidFill"), ctx.theme), _int(ln.get("w"), 12700))
                if not bdr or not bdr[0] or bdr[0][3] == 0:
                    continue
                seg = {"lnL": (cx, cy, cx, cy + ch), "lnR": (cx + cw, cy, cx + cw, cy + ch),
                       "lnT": (cx, cy, cx + cw, cy), "lnB": (cx, cy + ch, cx + cw, cy + ch)}[side]
                ctx.draw.line(seg, fill=tuple(bdr[0]), width=max(1, int(ctx.px(bdr[1]))))
            tx = _kid(tc, "txBody")
            if tx is not None and tc.get("vMerge") != "1":
                prepare(tx, tcpr, txt)
                _layout_text(ctx, tx, (cx, cy, cw, ch), chain_cell, txt.get("color"))
            cx += cw
        cy += heights[ri]


def _draw_chart_box(ctx, gd, part, box):
    x, y, w, h = box
    title = ""
    try:
        from lxml import etree
        cel = _kid(gd, "chart")
        rid = cel.get("{%s}id" % R) if cel is not None else None
        if rid:
            cx = etree.fromstring(part.related_part(rid).blob)
            t = cx.find(".//{http://schemas.openxmlformats.org/drawingml/2006/chart}title")
            if t is not None:
                title = " ".join(e.text or "" for e in t.iter(_a("t"))).strip()
    except Exception:
        pass
    ctx.draw.rounded_rectangle((x, y, x + w, y + h), radius=ctx.px(60000), fill=(245, 246, 248, 255),
                               outline=(205, 208, 214, 255), width=max(1, int(ctx.px(12700))))
    label = (title + "  (chart)") if title else "Chart"
    f, _ = FONTS.get("calibri", max(10, min(h / 8, ctx.px(EMU_PER_PT * 20))))
    ctx.draw.text((x + w / 2, y + h / 2), label, font=f, fill=(110, 114, 122, 255), anchor="mm")


def _draw_smartart(ctx, fr, part, xf, group):
    """SmartArt: PowerPoint saves the drawn diagram as plain shapes ('drawing' part) — draw those."""
    from lxml import etree
    drawing = None
    try:
        dm_rid = None
        rel_ids = _path(fr, "graphic", "graphicData", "relIds")
        if rel_ids is not None:
            dm_rid = rel_ids.get("{%s}dm" % R)
        drawings = [r for r in part.rels.values() if r.reltype == RT_DIAGRAM_DRAWING]
        if dm_rid:
            dm = etree.fromstring(part.related_part(dm_rid).blob)
            ext = None
            for e in dm.iter():
                if _local(e) == "dataModelExt" and e.get("relId"):
                    ext = e.get("relId")
            if ext and ext in part.rels:
                drawing = part.related_part(ext)
        if drawing is None and len(drawings) == 1:
            drawing = drawings[0].target_part
    except Exception:
        drawing = None
    if drawing is None:
        return False
    root = etree.fromstring(drawing.blob)
    tree = None
    for e in root.iter():
        if _local(e) == "spTree":
            tree = e
            break
    if tree is None:
        return False
    g = _Group(group, [xf[0], xf[1], xf[2], xf[3]], (0, 0), (xf[2] or 1, xf[3] or 1))
    for sp in tree:
        if _local(sp) == "sp":
            try:
                _draw_shape(ctx, sp, drawing, "smartart", g)
            except Exception:
                continue
    return True


# ══════════════════════════════════════════════════════════════════════
#   background
# ══════════════════════════════════════════════════════════════════════
def _draw_background(ctx):
    for obj in (ctx.slide, ctx.layout, ctx.master):
        bg = _path(obj._element, "cSld", "bg")
        if bg is None:
            continue
        bgpr = _kid(bg, "bgPr")
        fill = None
        if bgpr is not None:
            fill = fill_of(bgpr, ctx.theme, obj.part)
        else:
            ref = _kid(bg, "bgRef")
            if ref is not None:
                idx = _int(ref.get("idx"))
                col = color(ref, ctx.theme)
                if idx >= 1001 and idx - 1001 < len(ctx.theme.bgfills):
                    fill = fill_of(_wrap(ctx.theme.bgfills[idx - 1001]), ctx.theme, ctx.theme.part, col)
                elif 1 <= idx <= len(ctx.theme.fills):
                    fill = fill_of(_wrap(ctx.theme.fills[idx - 1]), ctx.theme, ctx.theme.part, col)
                fill = fill or (("solid", col) if col else None)
        if fill and fill[0] != "none":
            layer = Image.new("RGBA", (ctx.W, ctx.H), (255, 255, 255, 255))
            _paint(ctx, layer, fill, ("prst", "rect", {}), ctx.W, ctx.H)
            ctx.img.alpha_composite(layer)
            return


# ══════════════════════════════════════════════════════════════════════
#   public
# ══════════════════════════════════════════════════════════════════════
_PRS_CACHE = {}
_PRS_LOCK = threading.Lock()


def _open(path):
    from pptx import Presentation
    key = (os.path.abspath(path), os.path.getmtime(path))
    with _PRS_LOCK:
        prs = _PRS_CACHE.get(key)
        if prs is None:
            prs = Presentation(path)
            _PRS_CACHE.clear()          # one deck at a time is plenty
            _PRS_CACHE[key] = prs
    return prs


def visible_slides(path):
    """Indexes of the slides PowerPoint would show (hidden ones left out)."""
    prs = _open(path)
    return [i for i, s in enumerate(prs.slides) if s._element.get("show") != "0"]


def render_slide(path: str, index: int, out_png: str) -> list:
    """Draw slide `index` (0-based, in the file) to out_png; return its words as page fractions
    [{x, y, w, h, t}] for the board's selectable text layer."""
    prs = _open(path)
    with _PRS_LOCK:                      # python-pptx objects aren't thread-safe; tables are edited in place
        slide = prs.slides[index]
        ctx = _Ctx(prs, slide, index)
        _draw_background(ctx)
        show_master = slide._element.get("showMasterSp") != "0"
        show_master_on_layout = ctx.layout._element.get("showMasterSp") != "0"
        tree = lambda o: list(_path(o._element, "cSld", "spTree")) if _path(o._element, "cSld", "spTree") is not None else []  # noqa: E731
        if show_master and show_master_on_layout:
            _draw_tree(ctx, tree(ctx.master), ctx.master.part, "master")
        if show_master:
            _draw_tree(ctx, tree(ctx.layout), ctx.layout.part, "layout")
        _draw_tree(ctx, tree(slide), slide.part, "slide")
        words = list(ctx.words)
        W, H = ctx.W, ctx.H
        final = ctx.img.convert("RGB").resize((W // SS, H // SS), Image.LANCZOS)
    final.save(out_png, format="PNG", compress_level=1)
    return [{"x": round(x / W, 5), "y": round(y / H, 5), "w": round(w / W, 5), "h": round(h / H, 5), "t": t}
            for x, y, w, h, t in words if w > 0 and h > 0]
