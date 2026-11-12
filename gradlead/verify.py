"""Evidence-only email checks. We never guess addresses, so verification asks two questions:

1. Does the domain accept mail? (MX lookup, from researcher/leadgen/verify.py)
2. Is the address really on the page the profiler cited? (fetch email_source_url � HTML or a paper PDF �
   undo obfuscation and expand grouped author addresses like {alice, bob}@uni.edu)

3. (Optional) Does the mailbox exist? A self-hosted Reacher backend (REACHER_URL) checks it over SMTP.
   It only judges an address that was already published: a rejected mailbox becomes `invalid`, and a
   deliverable one upgrades `unconfirmed` (page unreadable from here, or JS-rendered) to `confirmed`.

Only `confirmed` addresses are exported by default.

Statuses:
  confirmed    - address found on its source page and the domain has mail servers
  unconfirmed  - domain OK, but the page couldn't be read or renders the address with JavaScript/images;
                 not exported unless asked for explicitly (export --email-status confirmed,unconfirmed)
  invalid      - bad syntax, no mail server, or the page was read and the address is not on it
"""
import base64
import binascii
import html
import io
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from gradlead import crawl, providers
from gradlead.normalize import deobfuscate, email_domain, is_valid_email

try:  # optional dependency
    import dns.exception
    import dns.resolver
except ImportError:  # pragma: no cover - exercised only without dnspython
    dns = None


def mx_hosts(domain: str) -> list[str] | None:
    """MX hosts sorted by preference; [] if the domain has none; None if DNS is unavailable."""
    if dns is None:
        return None
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=4)
        return [str(r.exchange).rstrip(".") for r in sorted(answers, key=lambda r: r.preference)]
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        try:  # RFC 5321 implicit MX: an A record is enough to receive mail
            dns.resolver.resolve(domain, "A", lifetime=4)
            return [domain]
        except dns.exception.DNSException:
            return []
    except dns.exception.DNSException:
        return None


def _pdf_text(data: bytes) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - pypdf is in requirements.txt
        return None
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:2])  # author block is on page 1
    except Exception:  # noqa: BLE001 - a broken PDF just means "unreadable"
        return None


def _ssl_context() -> ssl.SSLContext:
    """Verify certificates the way the OS does. Plain Python on Windows rejects sites that send an
    incomplete chain (uva.nl, uni-saarland.de), which browsers accept by fetching the missing link."""
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:  # pragma: no cover - truststore is in requirements.txt
        return ssl.create_default_context()


def fetch_page(url: str) -> str | None:
    """Raw HTML (so mailto: links count) or the first pages of a PDF as text; None if unreadable."""
    data = ctype = None
    for timeout in (10, 25):  # second, slower try: several sessions share this connection
        try:
            req = urllib.request.Request(url, headers={"User-Agent": crawl.UA})
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                ctype = resp.headers.get("Content-Type") or ""
                data = resp.read(15_000_000)
            break
        except urllib.error.HTTPError:  # blocked (403) or missing (404): a retry won't help
            return None
        except Exception:  # noqa: BLE001 - timeout or connection reset: try once more
            continue
    if data is None:
        return None
    if "pdf" in ctype or data[:5] == b"%PDF-":
        return _pdf_text(data)
    return data.decode("utf-8", errors="replace")


GROUPED = re.compile(r"\{([^{}]{1,400})\}\s*@\s*([\w-]+(?:\.[\w-]+)+)")


def expand_grouped(text: str) -> str:
    """'{hanan.aldarmaki, alham.fikri}@mbzuai.ac.ae' -> 'hanan.aldarmaki@mbzuai.ac.ae alham.fikri@mbzuai.ac.ae'."""
    def repl(m: re.Match) -> str:
        users = [u.strip() for u in re.split(r"[,;|\s]+", m.group(1)) if u.strip()]
        return " " + " ".join(f"{u}@{m.group(2)}" for u in users) + " "
    return GROUPED.sub(repl, text)


AT_IMAGE = re.compile(r"(?<=[\w.+-])\s*<img[^>]*>\s*(?=[\w-]+(?:\.[\w-]+)+)")


BARE_AT = re.compile(r"(?<![\w.])([\w][\w.+-]*)\s+(?:at|AT)\s+([\w-]+(?:\.[\w-]+)+)(?![\w-])")


B64_ATTR = re.compile(r'data-(?:encoded|email|mail|contact|address)="([A-Za-z0-9+/=]{12,})"')
CF_EMAIL = re.compile(r'data-cfemail="([0-9a-fA-F]{6,})"|/cdn-cgi/l/email-protection#([0-9a-fA-F]{6,})')


def decode_script_hidden(raw: str) -> str:
    """Addresses a browser would reveal with JavaScript: base64 data attributes (rug.nl) and
    Cloudflare email protection (hex string XORed with its first byte)."""
    out = []
    for m in B64_ATTR.finditer(raw):
        try:
            out.append(base64.b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4)).decode("utf-8", "ignore"))
        except (ValueError, binascii.Error):
            continue
    for m in CF_EMAIL.finditer(raw):
        hexed = m.group(1) or m.group(2)
        try:
            data = bytes.fromhex(hexed)
        except ValueError:
            continue
        out.append("".join(chr(b ^ data[0]) for b in data[1:]))
    return html.unescape(" ".join(out))


def views(raw: str) -> list[str]:
    """The page as a reader sees it, several ways: sites publish addresses as HTML character codes
    (yqsong&#x0040;cse&#x002E;ust&#x002E;hk), split across tags, URL-encoded in mailto links, or with
    the '@' drawn as an image (xusun<img ...>pku.edu.cn)."""
    decoded = html.unescape(urllib.parse.unquote(raw)) + " " + decode_script_hidden(raw)
    with_at = AT_IMAGE.sub("@", decoded)
    joined = re.sub(r"<[^>]+>", "", with_at)          # tags removed without spaces: user<span>@</span>domain
    text = crawl._text(with_at)
    bare_at = BARE_AT.sub(lambda m: m.group(1) + "@" + m.group(2), text)  # "wanxiaojun at pku.edu.cn"
    out = []
    for v in (decoded, with_at, joined, text, bare_at):
        v = expand_grouped(deobfuscate(v)).lower()
        out.append(re.sub(r"(?<=[\w.])-\s*\n\s*(?=[\w.])", "", v))  # PDF line-break hyphenation
    return out


def on_page(email: str, raw: str) -> bool:
    email = email.lower()
    user, domain = email.split("@", 1)
    for text in views(raw):
        if email in text:
            return True
        # Some sites build the address from separate user and domain spans.
        if user in text and domain in text and f"mailto:{user}" in text.replace(" ", ""):
            return True
    return False


def published_addresses(raw: str) -> list[str]:
    found: set[str] = set()
    for text in views(raw):
        found.update(crawl.find_emails(text.replace("mailto:", " ")))
    return sorted(found)


def verify(email: str, source_url: str | None) -> dict:
    if not is_valid_email(email):
        return {"status": "invalid", "detail": "bad syntax"}
    if not source_url:
        return {"status": "invalid", "detail": "no source_url: unpublished addresses are not allowed"}
    hosts = mx_hosts(email_domain(email))
    if hosts == []:
        return {"status": "invalid", "detail": "domain has no mail server"}
    mx_note = "MX ok" if hosts else "MX not checked (DNS unavailable)"
    raw = fetch_page(source_url)
    if raw is None:
        page = {"status": "unconfirmed", "detail": f"source page unreadable from here; {mx_note}"}
    elif on_page(email, raw):
        page = {"status": "confirmed", "detail": f"found on {source_url}; {mx_note}"}
    else:
        others = [e for e in published_addresses(raw) if email_domain(e) == email_domain(email)]
        if others:  # the page publishes addresses at this domain, just not this one: likely a mix-up
            return {"status": "invalid", "detail": f"not on {source_url}, which lists {', '.join(others[:3])}; re-check"}
        page = {"status": "unconfirmed", "detail": f"not in static HTML (page may render it with JS); {mx_note}"}
    return with_mailbox_check(email, page)


def with_mailbox_check(email: str, page: dict) -> dict:
    """Combine the page check with Reacher's SMTP answer, when a Reacher backend is configured."""
    mailbox = providers.reacher_verify(email) if hosts_ok(page) else None
    if mailbox == "invalid":
        return {"status": "invalid", "detail": page["detail"] + "; mailbox rejected (Reacher)"}
    if mailbox == "deliverable":
        return {"status": "confirmed", "detail": page["detail"] + "; mailbox deliverable (Reacher)"}
    if mailbox == "catch_all":
        return {**page, "detail": page["detail"] + "; catch-all domain (Reacher can't tell)"}
    return page


def hosts_ok(page: dict) -> bool:
    return "MX ok" in page["detail"] or "found on" in page["detail"]
