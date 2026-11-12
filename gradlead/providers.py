"""Self-hosted services shared with the B2B researcher (../researcher, docker-compose.reacher.yml).

- Search: SEARXNG_URL + SEARXNG_API_SECRET (free, self-hosted), else SERPER_API_KEY (paid Google results).
  `python3 -m gradlead search "<query>"` saves the Claude session's ~200-search budget.
- Mailbox check: REACHER_URL + REACHER_SECRET. Used by `verify` as a second opinion on a published
  address; it never creates or guesses one.

Keys come from gradresearch/.env, else ../researcher/.env (see load_env). Variables already set win.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 20
ROOT = Path(__file__).resolve().parent.parent
ENV_FILES = (ROOT / ".env", ROOT.parent / "researcher" / ".env")


def load_env(paths=ENV_FILES) -> None:
    """KEY=value lines into os.environ; earlier files and already-set variables win. Tolerates CRLF and comments."""
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip().removeprefix("export ").strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key and value and key not in os.environ:
                os.environ[key] = value


def _request(url: str, data: dict | None = None, headers: dict | None = None, timeout: int = TIMEOUT) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"_error": str(exc)}


# --- search ---------------------------------------------------------------------------------------

def searxng_search(query: str, num: int = 10) -> list[dict] | None:
    """Results from our SearXNG instance; None when SEARXNG_URL is unset."""
    url = os.environ.get("SEARXNG_URL")
    if not url:
        return None
    headers = {"X-Search-Secret": os.environ.get("SEARXNG_API_SECRET", ""), "User-Agent": "gradlead/1.0"}
    out: list[dict] = []
    seen: set[str] = set()
    for page in range(1, 4):  # ~10 results per page
        q = urllib.parse.urlencode({"q": query, "format": "json", "pageno": page})
        res = _request(f"{url.rstrip('/')}/search?{q}", headers=headers, timeout=30)
        if res.get("_error"):
            raise RuntimeError(f"SearXNG request failed: {res['_error']} (check SEARXNG_URL / SEARXNG_API_SECRET)")
        batch = [r for r in res.get("results") or [] if r.get("url") and r["url"] not in seen]
        for r in batch:
            seen.add(r["url"])
            out.append({"title": r.get("title"), "link": r["url"], "snippet": r.get("content")})
        if len(out) >= num or not batch:
            break
    return out[:num]


def serper_search(query: str, num: int = 10) -> list[dict] | None:
    key = os.environ.get("SERPER_API_KEY")
    if not key:
        return None
    res = _request("https://google.serper.dev/search", {"q": query, "num": num}, {"X-API-KEY": key})
    if res.get("_error"):
        raise RuntimeError(f"Serper request failed: {res['_error']}")
    return [{"title": r.get("title"), "link": r.get("link"), "snippet": r.get("snippet")} for r in res.get("organic") or []]


def web_search(query: str, num: int = 10, backend: str = "auto") -> list[dict] | None:
    """SearXNG first (free); Serper when SearXNG is unset, failing or empty. None when neither is configured."""
    serper_ok = backend != "searxng" and bool(os.environ.get("SERPER_API_KEY"))
    if backend != "serper" and os.environ.get("SEARXNG_URL"):
        try:
            results = searxng_search(query, num)
        except RuntimeError:
            if not serper_ok:
                raise
        else:
            if results or not serper_ok:
                return results
    return serper_search(query, num) if backend != "searxng" else None


# --- mailbox check --------------------------------------------------------------------------------

def reacher_verify(email: str) -> str | None:
    """deliverable | catch_all | invalid from a Reacher backend; None if unset, unreachable or inconclusive."""
    url = os.environ.get("REACHER_URL")
    if not url:
        return None
    # Cloudflare in front of the backend rejects urllib's default User-Agent.
    headers = {"x-reacher-secret": os.environ.get("REACHER_SECRET", ""), "User-Agent": "gradlead/1.0"}
    res = _request(url.rstrip("/") + "/v0/check_email", {"to_email": email}, headers, timeout=90)
    smtp = res.get("smtp") if isinstance(res.get("smtp"), dict) else {}
    reachable = res.get("is_reachable")
    if reachable == "invalid":
        return "invalid"
    if smtp.get("is_catch_all"):
        return "catch_all"
    if reachable == "safe" or (reachable == "risky" and smtp.get("is_deliverable")):
        return "deliverable"
    return None


def status() -> dict:
    keys = {k: bool(os.environ.get(k)) for k in ("SEARXNG_URL", "SERPER_API_KEY", "REACHER_URL")}
    keys["search_api"] = keys["SEARXNG_URL"] or keys["SERPER_API_KEY"]
    return keys
