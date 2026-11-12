from gradlead import scholarly


def test_abstract_reconstruction():
    assert scholarly.abstract_text({"hello": [0], "world": [1], "again": [3], "big": [2]}) == "hello world big again"
    assert scholarly.abstract_text(None) is None


def test_same_institution():
    assert scholarly.same_institution("University of Toronto", "The University of Toronto")
    assert scholarly.same_institution("KTH Royal Institute of Technology", "KTH Royal Institute of Technology, Stockholm")
    assert not scholarly.same_institution("University of Toronto", "University of Waterloo")


AUTHORS = {"results": [
    {"id": "https://openalex.org/A1", "display_name": "Jane Doe", "works_count": 80, "cited_by_count": 900,
     "summary_stats": {"h_index": 15}, "last_known_institutions": [{"display_name": "University of Toronto"}],
     "topics": [{"display_name": "Speech Recognition and Synthesis"}]},
    {"id": "https://openalex.org/A2", "display_name": "Jane Doe", "works_count": 10,
     "last_known_institutions": [{"display_name": "Some Other College"}]},
    {"id": "https://openalex.org/A3", "display_name": "John Smith", "works_count": 5, "last_known_institutions": []},
]}
WORKS = {"results": [
    {"id": "https://openalex.org/W1", "title": "Pidgin ASR", "publication_year": 2025, "doi": "https://doi.org/10.1/x",
     "primary_location": {"landing_page_url": "https://aclanthology.org/x", "source": {"display_name": "ACL"}},
     "abstract_inverted_index": {"Pidgin": [0], "speech": [1]}, "cited_by_count": 3},
]}


def test_lookup_disambiguates_by_institution(monkeypatch):
    calls = []

    def fake(path, params):
        calls.append((path, params))
        return AUTHORS if path == "authors" else WORKS

    monkeypatch.setattr(scholarly, "_openalex", fake)
    r = scholarly.lookup("Prof. Jane Doe", "University of Toronto")
    assert r["source"] == "openalex" and r["author"]["openalex_id"] == "A1"
    assert r["works"][0] == {**r["works"][0], "title": "Pidgin ASR", "venue": "ACL", "abstract": "Pidgin speech"}
    assert r["last_pub_year"] == 2025


def test_lookup_returns_candidates_when_ambiguous(monkeypatch):
    two = {"results": [AUTHORS["results"][0] | {"id": "https://openalex.org/A9", "works_count": 70}, AUTHORS["results"][0]]}
    monkeypatch.setattr(scholarly, "_openalex", lambda path, params: two)
    monkeypatch.setattr(scholarly, "_s2", lambda path, params: {"data": []})
    r = scholarly.lookup("Jane Doe", "University of Toronto")
    assert r["source"] is None and len(r["candidates"]["openalex"]) == 2
