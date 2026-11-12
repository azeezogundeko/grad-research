import copy
import json

import pytest

from gradlead import match, providers, verify
from gradlead.db import connect


@pytest.fixture
def applicant():
    a = copy.deepcopy(match.load_applicant())
    a["links"]["cv_url"] = "https://example.org/cv.pdf"
    return a


@pytest.fixture
def conn(tmp_path, monkeypatch, applicant):
    monkeypatch.setenv("GRADLEAD_DB", str(tmp_path / "test.db"))
    # No network in tests: every domain has MX unless it ends in .invalid; source pages come from PAGES.
    monkeypatch.setattr(verify, "mx_hosts", lambda domain: [] if domain.endswith(".invalid") else [f"mx.{domain}"])
    monkeypatch.setattr(verify, "fetch_page", lambda url: PAGES.get(url))
    monkeypatch.setattr(providers, "load_env", lambda *a, **k: None)
    for key in ("SEARXNG_URL", "SERPER_API_KEY", "REACHER_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(match, "load_applicant", lambda path=None: applicant)
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


PAGES: dict[str, str] = {}


def write_json(tmp_path, name, data):
    f = tmp_path / name
    f.write_text(json.dumps(data), encoding="utf-8")
    return str(f)


SPEECH_PAPERS = [
    {"title": "Code-switching speech recognition for low-resource African languages", "year": 2025,
     "venue": "Interspeech", "url": "https://doi.org/10.1/a",
     "abstract": "We study ASR for Yoruba and Nigerian Pidgin with self-supervised speech models."},
    {"title": "Multilingual text-to-speech for Hausa and Igbo", "year": 2024, "venue": "ACL",
     "url": "https://doi.org/10.1/b", "abstract": "A low-resource speech synthesis benchmark."},
    {"title": "Graph theory of nothing", "year": 2019, "venue": "X", "url": "https://doi.org/10.1/c", "abstract": ""},
]
