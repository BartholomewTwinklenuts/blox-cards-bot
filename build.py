# Downloads every Fighter card image from the Blox Cards wiki (Red, Blue,
# Green, Yellow), saves them in /images as .png, and writes Character.txt
# with one "Name{img link}" line per card, ready to paste into the bot.
import hashlib, io, os, re, time
import requests
from urllib.parse import unquote
from PIL import Image

API = "https://blox-cards.fandom.com/api.php"
PAGES = ["Red_Cards", "Blue_Cards", "Green_Cards", "Yellow_Cards"]
REPO = os.environ.get("GITHUB_REPOSITORY", "you/repo")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
OUT_DIR = "images"
MAX_WIDTH = 500  # shrink big images so the repo stays small

# Lines you always want at the top of Character.txt
EXTRA_LINES = [
    "Dmitri Shostakovich{img https://i.postimg.cc/tJ3VpnM2/IMG-2473.webp}",
]

s = requests.Session()
s.headers["User-Agent"] = "tracery-bot-image-mirror/1.0 (personal fan project)"


def api(params):
    params = {**params, "format": "json"}
    for attempt in range(5):
        try:
            r = s.get(API, params=params, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print("  retrying:", e)
            time.sleep(5 * (attempt + 1))
    raise SystemExit("Wiki API kept failing, try running again later.")


HEADING = re.compile(r"^\s*(=+)\s*(.*?)\s*\1\s*$")
WIKILINK = re.compile(r"\[\[\s*(?:File|Image)\s*:\s*([^|\]]+?)\s*(\|[^\]]*)?\]\]", re.I)
GALLERY = re.compile(r"^\s*(?:(?:File|Image)\s*:)?\s*([^|<>\[\]\n]+?\.(?:png|jpe?g|webp|gif))\s*(\|.*)?$", re.I)
BAD_WORDS = ("token", "legacy", "unused", "action", "terrain", "gear")
JUNK = r"(?:luna|card|fix|fixed|bordered|new art|new|re-?art|reborder|hd|namefix|v\d)"


def clean_name(n):
    n = n.replace("_", " ").strip()
    n = re.sub(r"\s*\([^)]*\)\s*$", "", n)  # drop "(Legacy)", "(Necrosyndicates)" etc.
    return n.strip()


def name_from_file(f):
    n = re.sub(r"\.\w+$", "", f).replace("_", " ")
    n = re.sub(r"\(\d+\)", "", n)
    for _ in range(3):
        n = re.sub(rf"\s*\b{JUNK}\b\s*$", "", n, flags=re.I)
    return n.strip()


def parse_options(opts):
    parts = [p.strip() for p in (opts or "").split("|") if p.strip()]
    for p in parts:
        if p.lower().startswith("link="):
            return p[5:]
    for p in reversed(parts):
        if "=" in p or re.fullmatch(r"\d*x?\d+px|thumb|right|left|center|frameless", p, re.I):
            continue
        return p
    return None


def fighters_on_page(page):
    text = api({"action": "parse", "page": page, "prop": "wikitext"})["parse"]["wikitext"]["*"]
    stack, found = [], []
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            level = len(m.group(1))
            stack = [h for h in stack if h[0] < level] + [(level, m.group(2).lower())]
            continue
        titles = " ".join(h[1] for h in stack)
        if "fighter" not in titles or any(w in titles for w in BAD_WORDS):
            continue
        matches = WIKILINK.findall(line) or ([GALLERY.match(line).groups()] if GALLERY.match(line) else [])
        for f, opts in matches:
            f = unquote(f.strip()).replace(" ", "_")
            f = f[0].upper() + f[1:]
            name = parse_options(opts)
            name = clean_name(name) if name else name_from_file(f)
            if name:
                found.append((name, f))
    return found


def image_urls(files):
    urls = {}
    for i in range(0, len(files), 50):
        batch = files[i:i + 50]
        data = api({"action": "query", "prop": "imageinfo", "iiprop": "url", "redirects": 1,
                    "titles": "|".join("File:" + f for f in batch)})["query"]
        alias = {x["from"]: x["to"] for x in data.get("normalized", []) + data.get("redirects", [])}
        pages = {p["title"]: p for p in data.get("pages", {}).values()}
        for f in batch:
            t = "File:" + f
            for _ in range(3):
                t = alias.get(t, t)
            t = alias.get(t.replace("_", " "), t.replace("_", " "))
            p = pages.get(t)
            if p and p.get("imageinfo"):
                urls[f] = p["imageinfo"][0]["url"]
    return urls


def slug(name, used):
    base = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or hashlib.md5(name.encode()).hexdigest()[:10]
    s_ = base
    n = 2
    while s_.lower() in used:
        s_ = f"{base}_{n}"
        n += 1
    used.add(s_.lower())
    return s_


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cards, seen, merged = [], set(), []
    for page in PAGES:
        found = fighters_on_page(page)
        print(f"{page}: {len(found)} fighter images")
        for name, f in found:
            if name.lower() in seen:
                merged.append(name)
                continue
            seen.add(name.lower())
            cards.append((name, f))
    print(f"{len(cards)} unique fighters, {len(merged)} duplicates/alt arts merged")

    urls = image_urls([f for _, f in cards])
    used, lines, missing = set(), list(EXTRA_LINES), []
    for i, (name, f) in enumerate(cards, 1):
        url = urls.get(f)
        if not url:
            missing.append(f"{name} ({f}) - no image found")
            continue
        fname = slug(name, used) + ".png"
        path = os.path.join(OUT_DIR, fname)
        if not os.path.exists(path):
            try:
                r = s.get(url, timeout=60)
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content))
                img.load()
                if img.width > MAX_WIDTH:
                    img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA")
                img.save(path, "PNG", optimize=True)
            except Exception as e:
                missing.append(f"{name} ({f}) - download failed: {e}")
                continue
        lines.append(f"{name}{{img https://raw.githubusercontent.com/{REPO}/{BRANCH}/{OUT_DIR}/{fname}}}")
        if i % 100 == 0:
            print(f"  {i}/{len(cards)} done")

    with open("Character.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with open("missing.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(missing) + "\n")
    with open("merged.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(merged) + "\n")
    print(f"Character.txt: {len(lines)} lines. Missing: {len(missing)}")


if __name__ == "__main__":
    main()
