from datetime import date, timedelta

from conftest import SPEECH_PAPERS

from gradlead import match, positions, store

FUTURE = (date.today() + timedelta(days=40)).isoformat()
PAST = (date.today() - timedelta(days=3)).isoformat()

SPEECH_AD = {
    "url": "https://www.uu.nl/vacancies/1", "title": "PhD position: speech recognition for low-resource languages",
    "institution": "Utrecht University", "country": "Netherlands", "degree": "PhD", "funded": True,
    "deadline": FUTURE, "supervisor": "Jane Doe", "source": "university",
    "description": "Fully funded 4-year PhD on automatic speech recognition for low-resource and code-switching "
                   "multilingual speech, including African languages, with self-supervised speech models.",
}
CRYPTO_AD = {**SPEECH_AD, "url": "https://x/2", "title": "PhD in lattice cryptography", "supervisor": "Bob Lee",
             "description": "Post-quantum cryptography proofs and number theory."}


def test_score_ad(applicant):
    s = positions.score_ad(SPEECH_AD["title"], SPEECH_AD["description"], applicant)
    assert s["primary_area"] == "speech" and s["score"] >= positions.RELEVANT
    assert positions.score_ad(CRYPTO_AD["title"], CRYPTO_AD["description"], applicant)["score"] == 0


def test_status_for():
    assert positions.status_for(80, True, PAST) == "expired"
    assert positions.status_for(80, 0, FUTURE) == "unfunded"
    assert positions.status_for(80, None, None) == "relevant"
    assert positions.status_for(10, True, FUTURE) == "weak"


def test_add_positions_creates_university_and_supervisor(conn):
    r = store.add_positions(conn, [SPEECH_AD, CRYPTO_AD, {"title": "no url"}])
    assert r["added"] == 2 and len(r["problems"]) == 1
    assert r["new_professors"] == 1 and r["linked_to_professors"] == 1      # crypto ad isn't relevant: no new prof
    uni = store.find_university(conn, "Utrecht University")
    assert uni["region"] == "Europe"
    pid = r["positions"][0]["professor_id"]
    prof = store.get_professor(conn, pid)
    assert prof["status"] == "discovered" and prof["source_url"] == SPEECH_AD["url"]
    assert prof["signals"]["open_positions"][0]["url"] == SPEECH_AD["url"]
    listed = store.list_positions(conn, upcoming=True)
    assert [p["title"] for p in listed] == [SPEECH_AD["title"]] and listed[0]["days_left"] == 40
    # re-adding the same ad updates, doesn't duplicate
    assert store.add_positions(conn, [SPEECH_AD])["updated"] == 1


def test_position_links_existing_professor_and_survives_reprofile(conn):
    uid = store.add_universities(conn, [{"name": "Utrecht University", "country": "Netherlands"}])["ids"][0]
    pid = store.add_professors(conn, uid, [{"full_name": "Prof. Jane Doe", "title": "Assistant Professor",
                                            "source_url": "https://x"}])["ids"][0]
    store._insert_publications(conn, pid, SPEECH_PAPERS, "openalex")
    conn.execute("INSERT INTO signals (professor_id, last_pub_year) VALUES (?, 2025)", (pid,))
    store.add_positions(conn, [SPEECH_AD])
    r = store.save_profile(conn, pid, {"email": "j.doe@uu.nl", "email_source_url": "https://uu.nl/staff/jdoe"})
    assert r["breakdown"]["openings"] == 20
    assert len(store.get_professor(conn, pid)["signals"]["open_positions"]) == 1


def test_expired_position_gives_no_boost():
    assert match.openings_points({"open_positions": [{"funded": True, "degree": "PhD", "deadline": PAST}]}) == 0
    assert match.openings_points({"open_positions": [{"funded": True, "degree": "PhD", "deadline": FUTURE}]}) == 20


def test_title_terms_make_short_ads_relevant(applicant):
    s = positions.score_ad("Doctoral Student in Human-in-the-Loop Autonomous Systems",
                           "Design the next generation of human-in-the-loop autonomous systems.", applicant)
    assert s["primary_area"] == "hitl_agents" and s["score"] >= positions.RELEVANT


def test_refresh_links_newly_relevant(conn):
    weak = {**SPEECH_AD, "url": "https://x/3", "title": "PhD studentship", "supervisor": "Ann Lee",
            "description": "Work on speech."}
    store.add_positions(conn, [weak])
    conn.execute("UPDATE positions SET title = 'PhD in speech recognition for low-resource languages'")
    r = store.refresh_positions(conn)
    assert r["relevant"] == 1 and r["newly_linked"] == 1 and r["new_professors"] == 1
