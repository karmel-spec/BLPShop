#!/usr/bin/env python3
"""Snapshot the BLP Shop Policies Google Doc into the webapp (English only).

The source doc is bilingual: an English half followed by a Spanish mirror
that starts at the "CAPACITACIÓN" heading. We import ONLY the English half —
the app's EN/ES toggle now supplies Spanish from data/policies.es.json, so the
team no longer maintains the doc's Spanish section.

Each top-level (H1) heading becomes a section; H2/H3 become sub-headings in
the section body. YouTube links become inline click-to-play embeds; real
images are saved to assets/policies/. Writes data/policies.json.

Usage:
    python3 scripts/fetch_policies.py             # fetch live doc
    python3 scripts/fetch_policies.py cached.html  # parse a saved export
"""
import base64, datetime, html, json, os, re, sys, urllib.parse, urllib.request
from html.parser import HTMLParser

DOC_ID = "1PYw5R8o9k8iLtCIfRkWVcno2hqqYQcS5-8izyM4Fbsk"
DOC_URL = f"https://docs.google.com/document/d/{DOC_ID}/edit"
EXPORT_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=html"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(ROOT, "assets", "policies")
OUT_JSON = os.path.join(ROOT, "data", "policies.json")

# The Spanish mirror begins here — stop importing at this heading.
STOP_RE = re.compile(r"^(CAPACITACI|SEGURIDAD|C[ÓO]DIGO DE|AMBIENTE LABORAL)", re.I)
# ...but the mirror also has heading-less Spanish front-matter (team-culture /
# roles paragraphs), so we additionally cut at the first block whose text is
# unmistakably Spanish (2+ accented chars / inverted punctuation).
ACCENTED = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]")
ES_WORDS = re.compile(r"\b(de|del|la|el|los|las|para|con|una|nuestro|nuestra|equipo|aquí|normas)\b", re.I)
BLOCKS = {"p", "ul", "ol", "li", "table", "tr", "td", "th"}


def is_spanish(text):
    return bool(ACCENTED.search(text) and ES_WORDS.search(text))


def cut_at_spanish(body_html):
    """Truncate the doc body at the start of the Spanish half."""
    import html as H
    for m in re.finditer(r"<(p|li|h[1-6])[^>]*>(.*?)</\1>", body_html, re.S):
        text = H.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        if is_spanish(text) or (m.group(1) == "h1" and STOP_RE.match(text.strip())):
            return body_html[:m.start()]
    return body_html


def unwrap(url):
    if url.startswith("https://www.google.com/url"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q")
        if q:
            return q[0]
    return url


def parse_youtube(url):
    u = urllib.parse.urlparse(url)
    host = u.netloc.lower()
    if "youtube.com" not in host and "youtu.be" not in host:
        return None
    qs = urllib.parse.parse_qs(u.query)
    vid = qs.get("v", [None])[0]
    if not vid:
        parts = [p for p in u.path.split("/") if p]
        if "youtu.be" in host and parts:
            vid = parts[0]                       # youtu.be/<id>
        elif parts and parts[0] in ("shorts", "embed", "v", "live"):
            vid = parts[1] if len(parts) > 1 else None  # /shorts/<id>, /embed/<id>
    if not vid:
        return None
    start = 0
    tt = qs.get("t", [""])[0]
    if tt:
        m = re.fullmatch(r"(?:(\d+)m)?(\d+)s?", tt)
        if m:
            start = int(m.group(1) or 0) * 60 + int(m.group(2))
    return vid, start


def style_classes(css):
    props = {}
    for m in re.finditer(r"\.(c\d+)\{([^}]*)\}", css):
        cls, body = m.group(1), m.group(2)
        s = set()
        if "font-weight:700" in body: s.add("b")
        if "font-style:italic" in body: s.add("i")
        if "text-decoration:underline" in body: s.add("u")
        if s:
            props[cls] = s
    return props


class DocCleaner(HTMLParser):
    def __init__(self, fmt_classes):
        super().__init__(convert_charrefs=True)
        self.fmt = fmt_classes
        self.sections = []
        self.cur = None
        self.done = False       # True once the Spanish mirror starts
        self.heading = None
        self.heading_lvl = 0
        self.heading_imgs = []
        self.heading_videos = []   # youtube links embedded inside a heading
        self.span_stack = []
        self.link = None
        self.pending_videos = []
        self.block_stack = []
        self.img_n = 0
        self.saved_images = []

    def out(self, s):
        if self.cur is not None:
            self.cur["html"].append(s)

    def flush_videos(self):
        for v in self.pending_videos:
            self.out(
                f'<div class="hbvid" data-yt="{v["id"]}" data-start="{v["start"]}" '
                f'data-title="{html.escape(v["title"], quote=True)}"></div>'
            )
            if self.cur is not None:
                self.cur["videos"] += 1
        self.pending_videos = []

    def start_section(self, title):
        self.cur = {"num": "", "title": title, "html": [], "videos": 0}
        self.sections.append(self.cur)

    def handle_img(self, attrs):
        a = dict(attrs)
        src = a.get("src", "")
        if self.heading is None and self.cur is None:
            return None  # front-matter imagery (before the first section)
        if src.startswith("data:image/"):
            ext = re.match(r"data:image/(\w+);base64,", src)
            if not ext:
                return None
            self.img_n += 1
            fname = f"pol-{self.img_n:02d}.{ext.group(1)}"
            os.makedirs(ASSET_DIR, exist_ok=True)
            with open(os.path.join(ASSET_DIR, fname), "wb") as f:
                f.write(base64.b64decode(src.split(",", 1)[1]))
            self.saved_images.append(fname)
            return f'<img class="hbimg" src="assets/policies/{fname}" loading="lazy" alt="">'
        return None  # drawings / external images dropped

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading = []
            self.heading_lvl = int(tag[1])
            self.heading_imgs = []
            self.heading_videos = []
            return
        if tag == "img":
            emit = self.handle_img(attrs)
            if not emit:
                return
            if self.heading is not None:
                self.heading_imgs.append(emit)
            elif self.cur is not None:
                self.out(emit)
            return
        if self.heading is not None:
            # a video linked from the heading text itself (e.g. "SAFETY (Intro Video)")
            if tag == "a":
                yt = parse_youtube(unwrap(dict(attrs).get("href", "")))
                if yt:
                    self.heading_videos.append(yt)
            return
        if tag == "a":
            href = unwrap(dict(attrs).get("href", ""))
            yt = parse_youtube(href)
            if yt:
                self.link = {"yt": yt, "text": []}
            elif href and not href.startswith("#"):
                self.link = {"href": href, "text": []}
            else:
                self.link = {"text": []}
            return
        if self.link is not None:
            return
        if tag == "span":
            fmts = set()
            for cls in (dict(attrs).get("class") or "").split():
                fmts |= self.fmt.get(cls, set())
            opened = []
            for f in ("b", "i", "u"):
                if f in fmts:
                    self.out(f"<{f}>")
                    opened.append(f)
            self.span_stack.append(opened)
            return
        if tag in BLOCKS:
            self.block_stack.append(tag)
            self.out(f"<{tag}>")
        elif tag == "br":
            self.out("<br>")

    def handle_endtag(self, tag):
        if self.done:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            title = re.sub(r"\s+", " ", "".join(self.heading or [])).strip()
            lvl = self.heading_lvl
            imgs, self.heading_imgs = self.heading_imgs, []
            hvids, self.heading_videos = self.heading_videos, []
            self.heading = None
            if not title:
                return
            if lvl == 1:
                self.flush_videos()
                if STOP_RE.match(title):   # Spanish mirror begins — stop
                    self.done = True
                    self.cur = None
                    return
                self.start_section(title)
            elif self.cur is not None:
                # H2 -> sub-heading, H3+ -> minor heading
                htag = "h3" if lvl == 2 else "h4"
                self.out(f"<{htag}>{html.escape(title)}</{htag}>")
            for im in imgs:
                self.out(im)
            # a video linked from the heading plays right below it
            vtitle = re.sub(r"\s*\([^)]*video[^)]*\)\s*$", "", title, flags=re.I).strip() or title
            for vid, start in hvids:
                self.pending_videos.append({"id": vid, "start": start, "title": vtitle})
            self.flush_videos()
            return
        if self.heading is not None:
            return
        if tag == "a":
            if self.link is not None:
                text = re.sub(r"\s+", " ", "".join(self.link["text"])).strip()
                if "yt" in self.link:
                    vid, start = self.link["yt"]
                    self.pending_videos.append({"id": vid, "start": start, "title": text or "Video"})
                elif "href" in self.link and text:
                    self.out(f'<a href="{html.escape(self.link["href"], quote=True)}" target="_blank" rel="noreferrer">{html.escape(text)}</a>')
                elif text:
                    self.out(html.escape(text))
            self.link = None
            return
        if self.link is not None:
            return
        if tag == "span":
            if self.span_stack:
                for f in reversed(self.span_stack.pop()):
                    self.out(f"</{f}>")
            return
        if tag in BLOCKS:
            if self.block_stack:
                self.block_stack.pop()
            self.out(f"</{tag}>")
            if not self.block_stack:
                self.flush_videos()

    def handle_data(self, data):
        if self.done:
            return
        if self.heading is not None:
            self.heading.append(data)
            return
        if self.link is not None:
            self.link["text"].append(data)
            return
        if self.cur is None:
            return
        text = data.replace("\xa0", " ")
        if text:
            self.out(html.escape(text))


def tidy(h):
    prev = None
    while prev != h:
        prev = h
        h = re.sub(r"<(p|li)>(?:\s|<br>|<b>|</b>|<i>|</i>|<u>|</u>)*</\1>", "", h)
        h = re.sub(r"</(ol|ul)>\s*<\1>", "", h)
    h = re.sub(r"\s{2,}", " ", h)
    return h.strip()


def main():
    if len(sys.argv) > 1:
        raw = open(sys.argv[1], encoding="utf-8").read()
        print(f"parsing local file {sys.argv[1]}")
    else:
        print(f"fetching {EXPORT_URL}")
        raw = urllib.request.urlopen(EXPORT_URL, timeout=60).read().decode("utf-8")

    css = re.search(r"<style[^>]*>(.*?)</style>", raw, re.S)
    cleaner = DocCleaner(style_classes(css.group(1)) if css else {})
    body = re.search(r"<body[^>]*>(.*)</body>", raw, re.S)
    cleaner.feed(cut_at_spanish(body.group(1) if body else raw))
    cleaner.flush_videos()

    slugs, sections = set(), []
    for s in cleaner.sections:
        base = "s" + re.sub(r"\W+", "-", s["title"].lower()).strip("-")[:24]
        slug = base
        n = 2
        while slug in slugs:
            slug = f"{base}-{n}"
            n += 1
        slugs.add(slug)
        sections.append({
            "slug": slug,
            "num": "",
            "title": s["title"],
            "videos": s["videos"],
            "html": tidy("".join(s["html"])),
        })

    out = {
        "generated": datetime.date.today().isoformat(),
        "source": DOC_URL,
        "sections": sections,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    total_videos = sum(s["videos"] for s in sections)
    print(f"wrote {OUT_JSON}: {len(sections)} sections, {total_videos} videos, "
          f"{len(cleaner.saved_images)} images -> assets/policies/")
    for s in sections:
        print(f"  {s['slug']:26s} {s['title'][:40]:42s} videos={s['videos']} len={len(s['html'])}")


if __name__ == "__main__":
    main()
