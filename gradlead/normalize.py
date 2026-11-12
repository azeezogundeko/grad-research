"""Name, title, email and text normalisation shared by the store, matcher and verifier."""
import re
import unicodedata

HONORIFICS = re.compile(r"^(prof(essor)?|dr|mr|mrs|ms|assoc|asst|assistant|associate|sir|dame)\.?\s+", re.I)
EMAIL_RE = re.compile(r"^[\w.+'-]+@[\w-]+(\.[\w-]+)+$")


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()


def name_key(name: str) -> str:
    """'Prof. Dr. José  Pérez-Ruiz' -> 'jose perez ruiz' (dedupe key for people and universities)."""
    text = ascii_fold(name).strip()
    while True:
        stripped = HONORIFICS.sub("", text)
        if stripped == text:
            break
        text = stripped
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def university_key(name: str) -> str:
    key = name_key(name)
    key = re.sub(r"\b(the|of|and|at|de|du|la)\b", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def name_tokens(name: str) -> set[str]:
    return {t for t in name_key(name).split() if len(t) > 1}


def same_person(a: str, b: str) -> bool:
    """Loose match for author disambiguation: same family name and a shared/initial-compatible given name."""
    ta, tb = name_key(a).split(), name_key(b).split()
    if not ta or not tb:
        return False
    last_a, last_b = ta[-1], tb[-1]
    # Chinese names are often written family-name first ("Wang Wei" vs "Wei Wang").
    if last_a != last_b and not (set(ta) == set(tb)):
        return False
    if set(ta) == set(tb):
        return True
    first_a, first_b = ta[0], tb[0]
    if first_a == first_b:
        return True
    # An initial matches a full given name ("J. Doe" / "Jane Doe"); two different full names never do
    # ("Hongsheng Li" is not "Hongyang Li").
    return min(len(first_a), len(first_b)) == 1 and first_a[0] == first_b[0]


def first_name(full_name: str) -> str:
    parts = name_key(full_name).split()
    raw = [p for p in re.split(r"\s+", ascii_fold(full_name).strip()) if p]
    raw = [p for p in raw if not HONORIFICS.match(p + " ")]
    if raw:
        return raw[0].strip(".,")
    return parts[0].title() if parts else ""


def last_name(full_name: str) -> str:
    raw = [p.strip(".,") for p in re.split(r"\s+", (full_name or "").strip()) if p]
    return raw[-1] if raw else ""


def seniority(title: str | None) -> str:
    """early | mid | senior | non_supervisor | emeritus | unknown — order of checks matters."""
    t = (title or "").lower()
    if not t:
        return "unknown"
    if "emerit" in t or "retired" in t:
        return "emeritus"
    if any(k in t for k in ("assistant prof", "tenure-track", "tenure track", "junior prof", "lecturer", "ramón y cajal",
                            "ramon y cajal", "research group leader", "group leader")) and "senior lecturer" not in t:
        return "early"
    if any(k in t for k in ("associate prof", "senior lecturer", "reader", "privatdozent")):
        return "mid"
    if "professor" in t or "chair" in t:
        return "senior"
    if any(k in t for k in ("postdoc", "research fellow", "research scientist", "researcher", "engineer", "phd student")):
        return "non_supervisor"
    return "unknown"


def deobfuscate(text: str) -> str:
    """Undo common academic email obfuscation: 'jdoe [at] cs [dot] uni [dot] edu', 'jdoe(at)uni.edu'."""
    s = text or ""
    s = re.sub(r"\s*(\[|\(|\{|<)\s*(at|AT|@)\s*(\]|\)|\}|>)\s*", "@", s)
    s = re.sub(r"\s*(\[|\(|\{|<)\s*(dot|DOT|\.)\s*(\]|\)|\}|>)\s*", ".", s)
    s = re.sub(r"(?<=[\w.])\s+(?:at|AT)\s+(?=[\w-]+\s+(?:dot|DOT)\s+)", "@", s)
    s = re.sub(r"(?<=[\w-])\s+(?:dot|DOT)\s+(?=[\w-])", ".", s)
    s = s.replace("＠", "@").replace("&#64;", "@").replace("&commat;", "@")
    return s


def is_valid_email(email: str | None) -> bool:
    return bool(email) and bool(EMAIL_RE.match(email.strip()))


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][\w'’-]*", text or ""))
