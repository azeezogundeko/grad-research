from conftest import SPEECH_PAPERS

from gradlead import funding, match

YEAR = 2026


def _score(applicant, title="Assistant Professor", pubs=SPEECH_PAPERS, signals=None, country="Canada", **prof):
    pubs = [{**p, "id": i + 1} for i, p in enumerate(pubs)]
    return match.score_professor({"title": title, **prof}, pubs, {"last_pub_year": 2025, **(signals or {})},
                                 country, applicant=applicant, year=YEAR)


def test_strong_speech_match(applicant):
    m = _score(applicant, signals={"accepting_students": "yes"})
    assert m["primary_area"] == "speech"
    assert m["classification"] == "strong"
    assert m["matched_papers"][:2] == [1, 2]       # old/unrelated paper is not a hook
    assert "vonative" in m["matched_projects"]
    assert m["inactive"] is None


def test_unrelated_professor_is_weak(applicant):
    pubs = [{"title": "Lattice cryptography proofs", "year": 2025, "abstract": "Number theory."}]
    m = _score(applicant, pubs=pubs, signals={"accepting_students": "yes"})
    assert m["score"] == 0 and m["classification"] == "weak" and m["primary_area"] is None


def test_not_accepting_and_old_work(applicant):
    yes = _score(applicant, signals={"accepting_students": "yes"})
    no = _score(applicant, signals={"accepting_students": "no"})
    assert yes["breakdown"]["openings"] - no["breakdown"]["openings"] == 40
    assert no["score"] < yes["score"]
    m = _score(applicant, signals={"last_pub_year": 2020})
    assert m["inactive"] == "no publication since 2020"


def test_funded_position_beats_accepting(applicant):
    pos = [{"title": "PhD in speech", "degree": "PhD", "funded": True, "url": "https://x"}]
    assert _score(applicant, signals={"open_positions": pos})["breakdown"]["openings"] == 20


def test_word_boundaries(applicant):
    # "asr" must not match inside "Kasra", "rag" not inside "storage"
    hits = match.term_hits("Kasra studies storage systems", applicant["areas"]["speech"]["terms"])
    assert not hits
    assert not match.term_hits("storage", applicant["areas"]["trustworthy_llm"]["terms"])


def test_secondary_area_and_trustworthy(applicant):
    pubs = [{"title": "Grounded citation generation reduces hallucination in LLMs", "year": 2025,
             "abstract": "Verifiable attribution for retrieval-augmented generation."}]
    m = _score(applicant, pubs=pubs)
    assert m["primary_area"] == "trustworthy_llm"
    assert "toyyib" in m["matched_projects"]


def test_funding_rules():
    assert funding.info("UK")["region"] == "Europe"
    assert funding.info("Hong Kong")["region"] == "China"
    assert funding.info("UAE")["region"] == "Middle East"
    assert funding.region_points("China") == 5 and funding.region_points("Netherlands") == 1
    assert funding.info("Atlantis")["region"] == "Other"


def test_ra_counts_as_student_role():
    pos = lambda d: {"open_positions": [{"funded": True, "degree": d, "url": "u"}]}
    assert match.openings_points(pos("RA")) == 20
    assert match.openings_points(pos("PhD/RA")) == 20
    assert match.openings_points(pos("Research Assistant")) == 20
    assert match.openings_points(pos("Postdoc")) == 0


def test_capped_area_tie_broken_by_raw_strength():
    from gradlead import match
    applicant = {"areas": {
        "a": {"label": "a", "terms": {"alpha": 3, "beta": 3, "gamma": 3, "delta": 3, "eps": 3}},
        "b": {"label": "b", "terms": {"one": 3, "two": 3, "three": 3, "four": 3, "five": 3, "six": 3, "seven": 3}},
    }, "projects": {}}
    prof = {"interests": ["alpha beta gamma delta eps", "one two three four five six seven"], "title": "Professor"}
    m = match.score_professor(prof, [], {}, None, applicant=applicant, year=2026)
    assert m["areas"]["a"]["score"] == m["areas"]["b"]["score"] == 60
    assert m["primary_area"] == "b"
