"""Read a professor's homepage / lab site or a faculty directory locally.

Copied from researcher/leadgen/crawl.py with academic link priorities. Uses crawl4ai when
installed (JS rendering, clean markdown) and falls back to urllib + a tiny HTML-to-text pass.
Running locally spends no web-search budget.

    python3 -m gradlead crawl 42                         # by professor id (homepage, else profile URL)
    python3 -m gradlead crawl https://cs.example.edu/people --max-pages 3
"""
import asyncio
import html
import re
import urllib.request
from urllib.parse import urljoin, urlparse

PRIORITY = [  # (keyword in URL path or link text, weight)
    ("prospective", 10), ("join", 10), ("opening", 10), ("position", 9), ("vacanc", 9), ("phd", 9),
    ("student", 8), ("contact", 8), ("about", 7), ("bio", 7), ("research", 7), ("publication", 7),
    ("people", 6), ("team", 6), ("member", 6), ("lab", 5), ("group", 5), ("project", 5), ("cv", 4),
    ("faculty", 6), ("staff", 5), ("directory", 5), ("teaching", 1),
]
SKIP = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|docx?|xlsx?|pptx?|mp4|mp3|bib|tar|gz)$|/(wp-content|tag|category|page/\d+)/|"
                  r"privacy|terms|cookie|login|signin|calendar|events?/", re.I)
MAX_CHARS_PER_PAGE = 6000
UA = "Mozilla/5.0 (compatible; GradResearchBot/1.0; academic outreach research)"


def score_link(url: str, text: str) -> int:
    hay = f"{urlparse(url).path} {text}".lower()
    return sum(w for k, w in PRIORITY if k in hay)


def pick_links(base: str, links: list[tuple[str, str]], limit: int) -> list[str]:
    host = urlparse(base).hostname or ""
    seen, ranked = set(), []
    for href, text in links:
        url = urljoin(base, href).split("#")[0].rstrip("/")
        h = urlparse(url).hostname or ""
        if not url.startswith("http") or h.removeprefix("www.") != host.removeprefix("www.") or SKIP.search(url):
            continue
        if url in seen or url == base.rstrip("/"):
            continue
        seen.add(url)
        s = score_link(url, text)
        if s > 0:
            ranked.append((s, url))
    ranked.sort(key=lambda x: -x[0])
    return [u for _, u in ranked[:limit]]


# --------------------------------------------------------------------------- fallback fetcher

def _fetch(url: str, timeout: float = 15) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if "html" not in (resp.headers.get("Content-Type") or "html"):
                return None
            return resp.read(2_000_000).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - any network/HTTP error just means "page unavailable"
        return None


def _links(raw: str) -> list[tuple[str, str]]:
    return [(m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))) for m in
            re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw, re.I | re.S)]


def _text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _crawl_urllib(start: str, max_pages: int, max_chars: int) -> list[dict]:
    raw = _fetch(start)
    if raw is None:
        return []
    pages = [{"url": start, "content": _text(raw)[:max_chars], "links": _links(raw)}]
    for url in pick_links(start, pages[0]["links"], max_pages - 1):
        sub = _fetch(url)
        if sub:
            pages.append({"url": url, "content": _text(sub)[:max_chars], "links": _links(sub)})
    return pages


# --------------------------------------------------------------------------- crawl4ai

async def _crawl4ai(start: str, max_pages: int, max_chars: int) -> list[dict]:
    from crawl4ai import AsyncWebCrawler  # imported lazily; optional dependency

    def links_of(result) -> list[tuple[str, str]]:
        internal = (getattr(result, "links", None) or {}).get("internal", [])
        return [(link.get("href", ""), link.get("text", "")) for link in internal if isinstance(link, dict)]

    def content_of(result) -> str:
        md = getattr(result, "markdown", None)
        text = getattr(md, "raw_markdown", None) or (str(md) if md else "") or getattr(result, "cleaned_html", "") or ""
        return text[:max_chars]

    pages = []
    async with AsyncWebCrawler() as crawler:
        home = await crawler.arun(url=start)
        if not getattr(home, "success", False):
            return []
        pages.append({"url": start, "content": content_of(home), "links": links_of(home)})
        for url in pick_links(start, pages[0]["links"], max_pages - 1):
            try:
                res = await crawler.arun(url=url)
            except Exception:  # noqa: BLE001
                continue
            if getattr(res, "success", False):
                pages.append({"url": url, "content": content_of(res), "links": []})
    return pages


def engine() -> str:
    try:
        import crawl4ai  # noqa: F401
        return "crawl4ai"
    except ImportError:
        return "urllib"


def find_emails(text: str) -> list[str]:
    """Addresses on the pages, including '[at]' / '(dot)' style obfuscation."""
    from gradlead.normalize import deobfuscate  # local import: normalize has no crawl dependency
    return sorted(set(e.lower().rstrip(".") for e in re.findall(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+", deobfuscate(text))))


def crawl(url: str, max_pages: int = 6, max_chars: int = MAX_CHARS_PER_PAGE) -> dict:
    start = url if "://" in url else "https://" + url
    used = engine()
    pages: list[dict] = []
    if used == "crawl4ai":
        try:
            pages = asyncio.run(_crawl4ai(start, max_pages, max_chars))
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail the research
            used = f"urllib (crawl4ai failed: {exc.__class__.__name__})"
    if not pages:
        pages = _crawl_urllib(start, max_pages, max_chars)
    all_text = "\n".join(p["content"] for p in pages)
    hrefs = " ".join(href for p in pages for href, _ in p.get("links", []))  # mailto: links are lost by _text
    return {
        "engine": used,
        "start_url": start,
        "pages_read": [p["url"] for p in pages],
        "emails": find_emails(all_text + " " + hrefs.replace("mailto:", " ")),
        "pages": [{"url": p["url"], "content": p["content"]} for p in pages],
        "research_depth": "site" if len(pages) >= 2 else ("partial" if pages else "search_only"),
    }
