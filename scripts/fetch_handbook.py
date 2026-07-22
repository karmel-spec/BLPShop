#!/usr/bin/env python3
"""Snapshot the BLP Restoration Handbook Google Doc into the webapp.

Downloads the doc's HTML export, strips Google's markup down to clean
semantic HTML, replaces every YouTube link + QR-code pair with an inline
video embed placeholder (the app renders a click-to-play player), saves
real images to assets/handbook/, and writes data/handbook.json.

Usage:
    python3 scripts/fetch_handbook.py            # fetch live doc
    python3 scripts/fetch_handbook.py cached.html  # parse a saved export
"""
import base64, datetime, html, json, os, re, sys, urllib.parse, urllib.request
from html.parser import HTMLParser

DOC_ID = "1at8y6h6pphLmAL5gaE2TzfHeDv5Xn9xdbWVdozvxhxA"
DOC_URL = f"https://docs.google.com/document/d/{DOC_ID}/edit"
EXPORT_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=html"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(ROOT, "assets", "handbook")
OUT_JSON = os.path.join(ROOT, "data", "handbook.json")

QR_SIZE = 96          # QR codes export as exactly 96x96 px images
BLOCKS = {"p", "ul", "ol", "li", "table", "tr", "td", "th"}


def unwrap(url):
    """Unwrap Google's /url?q= redirect."""
    if url.startswith("https://www.google.com/url"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q")
        if q:
            return q[0]
    return url


def parse_youtube(url):
    """Return (video_id, start_seconds) or None."""
    u = urllib.parse.urlparse(url)
    if "youtube.com" not in u.netloc and "youtu.be" not in u.netloc:
        return None
    qs = urllib.parse.parse_qs(u.query)
    vid = qs.get("v", [None])[0]
    if not vid and "youtu.be" in u.netloc:
        vid = u.path.lstrip("/").split("/")[0]
    if not vid:
        return None
    start = 0
    t = qs.get("t", [""])[0]
    if t:
        m = re.fullmatch(r"(?:(\d+)m)?(\d+)s?", t)
        if m:
            start = int(m.group(1) or 0) * 60 + int(m.group(2))
    return vid, start


def style_classes(css):
    """Map class name -> set of {'b','i','u'} from the export stylesheet."""
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
        self.sections = []      # {num, title, html:[...]}
        self.cur = None
        self.skip_index = False
        self.heading = None     # buffer while inside h1..h6
        self.heading_imgs = []  # images found inside a heading element
        self.span_stack = []    # inline tags opened per <span>
        self.link = None        # {url, text:[...]} while inside <a>
        self.pending_videos = []
        self.block_stack = []
        self.img_n = 0
        self.saved_images = []

    # ---- helpers ----
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
        m = re.match(r"(\d+[a-z]?)\.\s*(.*)", title)
        num = m.group(1) if m else ""
        self.cur = {"num": num, "title": title, "html": [], "videos": 0}
        self.sections.append(self.cur)

    # ---- images ----
    def handle_img(self, attrs):
        """Return the cleaned <img> HTML (saving the file), or None to drop."""
        a = dict(attrs)
        src = a.get("src", "")
        style = a.get("style", "")
        wm = re.search(r"width:\s*([\d.]+)px", style)
        hm = re.search(r"height:\s*([\d.]+)px", style)
        w = float(wm.group(1)) if wm else 0
        h = float(hm.group(1)) if hm else 0
        if abs(w - QR_SIZE) < 2 and abs(h - QR_SIZE) < 2:
            return None  # QR code — replaced by the inline video embed
        if self.heading is None and (self.cur is None or self.skip_index):
            return None  # front-matter / index imagery
        if src.startswith("data:image/"):
            ext = re.match(r"data:image/(\w+);base64,", src)
            if not ext:
                return None
            self.img_n += 1
            fname = f"hb-{self.img_n:02d}.{ext.group(1)}"
            os.makedirs(ASSET_DIR, exist_ok=True)
            with open(os.path.join(ASSET_DIR, fname), "wb") as f:
                f.write(base64.b64decode(src.split(",", 1)[1]))
            self.saved_images.append(fname)
            return f'<img class="hbimg" src="assets/handbook/{fname}" loading="lazy" alt="">'
        return None  # docs.google.com/drawings images are decorative dividers

    # ---- parser hooks ----
    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading = []
            self.heading_imgs = []
            return
        if tag == "img":
            emit = self.handle_img(attrs)
            if not emit:
                return
            if self.heading is not None:
                self.heading_imgs.append(emit)
            elif self.cur is not None and not self.skip_index:
                self.out(emit)
            return
        if self.heading is not None:
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
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            title = re.sub(r"\s+", " ", "".join(self.heading or [])).strip()
            imgs, self.heading_imgs = self.heading_imgs, []
            self.heading = None
            if not title:
                return
            if title.lower() == "index":
                self.skip_index = True
                self.cur = None
            elif re.match(r"\d+[a-z]?\.", title):
                self.skip_index = False
                self.flush_videos()
                self.start_section(title)
            elif self.cur is not None and not self.skip_index:
                self.out(f"<h3>{html.escape(title)}</h3>")
            for im in imgs:
                self.out(im)
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
        if self.heading is not None:
            self.heading.append(data)
            return
        if self.link is not None:
            self.link["text"].append(data)
            return
        if self.skip_index or self.cur is None:
            return
        text = data.replace("\xa0", " ")
        if text:
            self.out(html.escape(text))


def tidy(h):
    """Drop empty paragraphs/cells left over after removing QR codes."""
    prev = None
    while prev != h:
        prev = h
        h = re.sub(r"<(p|li)>(?:\s|<br>|<b>|</b>|<i>|</i>|<u>|</u>)*</\1>", "", h)
        h = re.sub(r"</(ol|ul)>\s*<\1>", "", h)  # Google exports one list element per item
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
    cleaner.feed(body.group(1) if body else raw)
    cleaner.flush_videos()

    slugs, sections = set(), []
    for s in cleaner.sections:
        base = "s" + (s["num"] or re.sub(r"\W+", "-", s["title"].lower())[:20])
        slug = base
        n = 2
        while slug in slugs:
            slug = f"{base}{'bcdefg'[n-2]}"
            n += 1
        slugs.add(slug)
        sections.append({
            "slug": slug,
            "num": s["num"],
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
          f"{len(cleaner.saved_images)} images -> assets/handbook/")
    for s in sections:
        print(f"  {s['slug']:6s} {s['title'][:60]:62s} videos={s['videos']} len={len(s['html'])}")


if __name__ == "__main__":
    main()
