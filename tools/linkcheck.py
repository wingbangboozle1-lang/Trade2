"""Build + link check. Fails loudly on a broken internal link or anchor."""
import os, re, sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.ids = set()
        self.scripts = []
        self.css = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.add(d["id"])
        if tag == "a" and d.get("href"):
            self.hrefs.append(d["href"])
        if tag == "script" and d.get("src"):
            self.scripts.append(d["src"])
        if tag == "link" and d.get("href") and "stylesheet" in (d.get("rel") or ""):
            self.css.append(d["href"])

pages = []
for dirpath, _dirs, files in os.walk(ROOT):
    if ".git" in dirpath or "node_modules" in dirpath:
        continue
    for f in files:
        if f.endswith(".html"):
            pages.append(os.path.relpath(os.path.join(dirpath, f), ROOT))

errors = []
checked = 0
for page in sorted(pages):
    path = os.path.join(ROOT, page)
    parser = Links()
    with open(path, encoding="utf-8") as fh:
        parser.feed(fh.read())
    base = os.path.dirname(page)
    for href in parser.hrefs:
        if href.startswith(("http://", "https://", "mailto:", "#")):
            if href.startswith("#") and len(href) > 1:
                target = os.path.join(ROOT, page)
                p2 = Links()
                with open(target, encoding="utf-8") as fh2:
                    p2.feed(fh2.read())
                if href[1:] not in p2.ids:
                    errors.append(f"{page}: missing anchor {href}")
            continue
        file_part, _, anchor = href.partition("#")
        if not file_part:
            continue
        target = os.path.normpath(os.path.join(base, file_part))
        checked += 1
        full = os.path.join(ROOT, target)
        if os.path.isdir(full):
            # A directory link (e.g. "docs/") is only valid on a static host if
            # it resolves to an index.html inside the repo.
            if not os.path.exists(os.path.join(full, "index.html")):
                errors.append(f"{page}: directory link without index.html -> {href}")
            continue
        if not os.path.exists(full):
            errors.append(f"{page}: broken link -> {href}")
            continue
        if anchor:
            p2 = Links()
            with open(os.path.join(ROOT, target), encoding="utf-8") as fh2:
                p2.feed(fh2.read())
            if anchor not in p2.ids:
                errors.append(f"{page}: broken anchor -> {href}")
    for asset in parser.scripts + parser.css:
        if asset.startswith("http"):
            continue
        target = os.path.normpath(os.path.join(base, asset))
        checked += 1
        if not os.path.exists(os.path.join(ROOT, target)):
            errors.append(f"{page}: missing asset -> {asset}")

print(f"pages={len(pages)} internal_links_checked={checked} errors={len(errors)}")
for e in errors:
    print("  ERROR", e)
sys.exit(1 if errors else 0)
