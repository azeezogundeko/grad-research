import conftest
from conftest import SPEECH_PAPERS

from gradlead import export, store, verify


def _uni(conn, name="University of Toronto", country="Canada"):
    return store.add_universities(conn, [{"name": name, "country": country, "goal": 10}])["ids"][0]


def _prof(conn, uid, **kw):
    rec = {"full_name": "Prof. Jane Doe", "title": "Assistant Professor", "source_url": "https://cs.x.edu/people", **kw}
    return store.add_professors(conn, uid, [rec])["ids"][0]


def _profiled(conn, email="jdoe@cs.toronto.edu"):
    uid = _uni(conn)
    pid = _prof(conn, uid)
    store._insert_publications(conn, pid, SPEECH_PAPERS, "openalex")
    conn.execute("INSERT INTO signals (professor_id, last_pub_year) VALUES (?, 2025)", (pid,))
    r = store.save_profile(conn, pid, {"email": email, "email_source_url": "https://cs.x.edu/~jdoe",
                                       "accepting_students": "yes", "accepting_quote": "I am recruiting PhD students",
                                       "accepting_url": "https://cs.x.edu/~jdoe"})
    return pid, r


def test_university_and_professor_dedupe(conn):
    uid = _uni(conn)
    assert _uni(conn, "The University of Toronto") == uid
    a = _prof(conn, uid)
    b = _prof(conn, uid, full_name="Jane Doe", homepage="https://jdoe.ca")
    assert a == b
    assert store.get_professor(conn, a)["homepage"] == "https://jdoe.ca"


def test_unsourced_email_is_dropped(conn):
    uid = _uni(conn)
    r = store.add_professors(conn, uid, [{"full_name": "A B", "source_url": "https://x", "email": "a@x.edu"},
                                         {"full_name": "No Source"}])
    assert r["added"] == 1 and len(r["skipped"]) == 2
    assert store.get_professor(conn, r["ids"][0])["email"] is None


def test_profile_matches_and_statuses(conn):
    pid, r = _profiled(conn)
    assert r["status"] == "matched" and r["classification"] == "strong"
    pid2 = _prof(conn, 1, full_name="Bob Lee")
    conn.execute("INSERT INTO signals (professor_id, last_pub_year) VALUES (?, 2025)", (pid2,))
    store._insert_publications(conn, pid2, SPEECH_PAPERS, "openalex")
    assert store.save_profile(conn, pid2, {"accepting_students": "yes"})["status"] == "no_email"
    assert "downgraded" in store.save_profile(conn, pid2, {"accepting_students": "yes"})["notes"][0]


def _draft(pid, conn, **kw):
    hook = conn.execute("SELECT id FROM publications WHERE professor_id = ? ORDER BY year DESC", (pid,)).fetchone()[0]
    body = ("Dear Prof. Doe,\n\nI read your Interspeech paper on code-switching speech recognition for low-resource "
            "African languages with real interest.\n\nIn building Vonative, a real-time voice-agent system for Nigerian "
            "telephony, I ran into the same problem from the deployment side: ASR hallucination on local-language audio, "
            "especially on Nigerian Pidgin and code-switched calls. I traced part of it to how the pipeline handled "
            "uncertain transcripts, and I would like to study it properly rather than patch it.\n\n"
            "I am applying for a thesis-based MSc or PhD position starting in 2027 and would be glad to work on "
            "robust ASR for code-switched African speech in your group. Are you taking new students for that intake?\n\n"
            "Best regards,")
    d = {"hook_publication_id": hook, "cv_project": "vonative", "programme": "PhD 2027",
         "subject": "Prospective PhD student: code-switched ASR", "body": body, **kw}
    return store.save_draft(conn, pid, d)


def test_draft_validation_and_signature(conn, applicant):
    pid, _ = _profiled(conn)
    r = _draft(pid, conn)
    assert r["saved"], r
    body = store.get_professor(conn, pid)["draft"]["body"]
    assert body.endswith(applicant["signature"]) and "{{cv_url}}" in body
    assert store.get_professor(conn, pid)["status"] == "drafted"


def test_draft_rejects_invented_numbers_and_placeholders(conn):
    pid, _ = _profiled(conn)
    bad = _draft(pid, conn, body="Dear Prof. Doe, I cut latency by 47% in Vonative. [NAME] " + "word " * 120)
    assert not bad["saved"]
    joined = " ".join(bad["errors"])
    assert "47" in joined and "placeholder" in joined
    assert not _draft(pid, conn, cv_project="nonexistent")["saved"]
    assert not _draft(pid, conn, hook_publication_id=9999)["saved"]


def test_verify_and_export(conn, tmp_path):
    pid, _ = _profiled(conn)
    assert _draft(pid, conn)["saved"]
    conftest.PAGES["https://cs.x.edu/~jdoe"] = "<p>Email: jdoe [at] cs [dot] toronto [dot] edu</p>" + "x" * 4000
    assert store.verify_emails(conn)["confirmed"] == 1
    rows = export.rows(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["email"] == "jdoe@cs.toronto.edu" and row["salutation"] == "Prof. Doe"
    assert "https://example.org/cv.pdf" in row["body"] and "{{" not in row["body"]
    assert list(row) == export.COLUMNS
    for fu in (row["followup_1_body"], row["followup_2_body"]):
        assert fu.startswith("Dear Prof. Doe,") and "{{" not in fu and "2027" in fu
    assert "https://example.org/cv.pdf" in row["followup_1_body"]
    assert "“" in export.to_csv(rows) or '"' not in row["body"]
    export.mark_exported(conn, [pid])
    assert export.rows(conn) == []          # already exported
    assert len(export.rows(conn, include_exported=True)) == 1


def test_wrong_email_on_page_is_invalid(conn):
    pid, _ = _profiled(conn, email="jane.doe@cs.toronto.edu")
    conftest.PAGES["https://cs.x.edu/~jdoe"] = "<a href='mailto:jdoe@cs.toronto.edu'>mail</a>"
    assert store.verify_emails(conn)["invalid"] == 1
    assert store.get_professor(conn, pid)["status"] == "no_email"


def test_suppression_blocks_export(conn):
    pid, _ = _profiled(conn)
    _draft(pid, conn)
    conn.execute("UPDATE professors SET email_status = 'confirmed'")
    store.suppress(conn, "cs.toronto.edu", "declined")
    assert export.rows(conn) == []
    assert store.get_professor(conn, pid)["status"] == "declined"


def test_targets_file(conn, tmp_path):
    t = tmp_path / "targets.txt"
    t.write_text("# c\nCanada|University of Toronto|20|DCS\nUAE|MBZUAI\n", encoding="utf-8")
    store.add_universities(conn, store.parse_targets(t))
    prog = store.target_progress(conn)
    assert {r["name"]: r["region"] for r in prog} == {"MBZUAI": "Middle East", "University of Toronto": "Canada"}
    assert store.target_progress(conn, pending="discover")[0]["to_discover"] > 0


def test_stats(conn):
    _profiled(conn)
    s = store.stats(conn)
    assert s["professors"] == 1 and s["match_class"] == {"strong": 1}
    assert store.stats(conn, "Canada")["professors"] == 1
    assert store.stats(conn, "Europe")["professors"] == 0


def test_on_page_mailto():
    assert verify.on_page("a@x.edu", "<a href='mailto:a@x.edu'>")
    assert not verify.on_page("a@x.edu", "<p>b@x.edu</p>")


def test_grouped_and_hyphenated_pdf_addresses():
    text = "Hanan Aldarmaki, Alham Fikri Aji\n{hanan.aldarmaki, alham.fikri}@mbzuai.ac.ae\n"
    assert verify.on_page("hanan.aldarmaki@mbzuai.ac.ae", text)
    assert verify.on_page("alham.fikri@mbzuai.ac.ae", text)
    assert verify.on_page("monojit.choudhury@mbzuai.ac.ae", "monojit.choud-\nhury@mbzuai.ac.ae")
    assert not verify.on_page("someone.else@mbzuai.ac.ae", text)


def test_pdf_source_is_read(monkeypatch):
    from io import BytesIO

    from pypdf import PdfWriter
    buf = BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.write(buf)
    assert verify._pdf_text(buf.getvalue()) == ""      # readable PDF (no text) -> "", not None
    assert verify._pdf_text(b"not a pdf") is None


def test_unconfirmed_not_exported_by_default(conn):
    pid, _ = _profiled(conn)
    _draft(pid, conn)
    conn.execute("UPDATE professors SET email_status = 'unconfirmed'")
    assert export.rows(conn) == []
    assert len(export.rows(conn, email_statuses=("confirmed", "unconfirmed"))) == 1


def test_on_page_handles_real_world_encodings():
    assert verify.on_page("yqsong@cse.ust.hk", '<p style="display:none">yqsong&#x0040;cse&#x002E;ust&#x002E;hk</p>')
    assert verify.on_page("xusun@pku.edu.cn", '<p>E-mail:xusun<img src="/_mediafile/f_h_pic.png" style="x">pku.edu.cn</p>')
    assert verify.on_page("wlam@se.cuhk.edu.hk", "<p>Email: wlam<span>@</span>se.cuhk.<wbr>edu.hk</p>")
    page = '<a href="mailto:dept%5BNO%20SPAM%5D@se.cuhk.edu.hk">x</a><p>Email: <b>wlam</b>@se.cuhk.edu.hk</p>'
    assert verify.on_page("wlam@se.cuhk.edu.hk", page)
    assert "5d@se.cuhk.edu.hk" not in verify.published_addresses(page)
    assert not verify.on_page("other@se.cuhk.edu.hk", page)


def test_reverify_restores_wrongly_invalid_email(conn):
    pid, _ = _profiled(conn)
    conn.execute("UPDATE professors SET email_status = 'invalid', status = 'no_email'")
    conftest.PAGES["https://cs.x.edu/~jdoe"] = "<p>jdoe&#x0040;cs&#x002E;toronto&#x002E;edu</p>"
    assert store.verify_emails(conn, pending=False)["confirmed"] == 1
    assert store.get_professor(conn, pid)["status"] == "matched"


def test_on_page_bare_at():
    assert verify.on_page("wanxiaojun@pku.edu.cn", "<p>Email: wanxiaojun at pku.edu.cn</p>")
    assert not verify.on_page("someone@pku.edu.cn", "<p>We met at pku.edu.cn offices</p>")


def test_drop_publications_rescores(conn):
    pid, r = _profiled(conn)
    before = r["score"]
    ids = [x[0] for x in conn.execute("SELECT id FROM publications WHERE professor_id = ? AND year >= 2024", (pid,))]
    out = store.drop_publications(conn, pid, ids)
    assert out["dropped"] == 2 and out["rematch"]["score"] < before
    assert store.drop_publications(conn, pid, source="openalex")["dropped"] == 1


def test_cannot_drop_hook_paper(conn):
    import pytest
    pid, _ = _profiled(conn)
    assert _draft(pid, conn)["saved"]
    hook = conn.execute("SELECT hook_publication_id FROM drafts WHERE professor_id = ?", (pid,)).fetchone()[0]
    with pytest.raises(ValueError):
        store.drop_publications(conn, pid, [hook])


def test_confirmed_email_not_downgraded_when_page_unreachable(conn):
    pid, _ = _profiled(conn)
    conn.execute("UPDATE professors SET email_status = 'confirmed'")
    conftest.PAGES.pop("https://cs.x.edu/~jdoe", None)          # page now unreachable
    r = store.verify_emails(conn, pending=False)
    assert r.get("kept_confirmed") == 1
    assert store.get_professor(conn, pid)["email_status"] == "confirmed"


def test_on_page_script_hidden_addresses():
    import base64
    enc = base64.b64encode(b'<a href="mailto:a.bisazza@rug.nl">a.bisazza@rug.nl</a>').decode()
    assert verify.on_page("a.bisazza@rug.nl", f'<span class="js--decode" data-encoded="{enc}">a.bisazza rug.nl</span>')
    key = 0x5A
    cf = bytes([key]) + bytes(b ^ key for b in b"jane@uni.edu")
    assert verify.on_page("jane@uni.edu", f'<a class="__cf_email__" data-cfemail="{cf.hex()}">[email protected]</a>')
    assert not verify.on_page("bob@uni.edu", f'<a data-cfemail="{cf.hex()}">x</a>')


def test_hook_ref_shortens_and_cleans_titles():
    assert export._hook_ref("PingPong: A Natural Benchmark for Multi-Turn Code-Switching Dialogues") == "your paper “PingPong”"
    assert export._hook_ref("Towards AI-$45^{\circ}$ Law") == "your paper “Towards AI-45° Law”"
    assert export._hook_ref("") == "your recent work"


def test_reacher_second_opinion(monkeypatch):
    from gradlead import providers
    page = {"status": "unconfirmed", "detail": "source page unreadable from here; MX ok"}
    monkeypatch.setattr(providers, "reacher_verify", lambda e: "deliverable")
    assert verify.with_mailbox_check("a@x.edu", page)["status"] == "confirmed"
    monkeypatch.setattr(providers, "reacher_verify", lambda e: "invalid")
    assert verify.with_mailbox_check("a@x.edu", {"status": "confirmed", "detail": "found on u; MX ok"})["status"] == "invalid"
    monkeypatch.setattr(providers, "reacher_verify", lambda e: None)
    assert verify.with_mailbox_check("a@x.edu", page) == page


def test_single_block_body_rejected(conn):
    pid, _ = _profiled(conn)
    one_block = ("Dear Prof. Doe,\n\nI read your Interspeech paper on code-switching speech recognition for low-resource "
                 "African languages with real interest. In building Vonative, a real-time voice-agent system for Nigerian "
                 "telephony, I ran into ASR hallucination on local-language audio, especially on Nigerian Pidgin and "
                 "code-switched calls, and I would like to study it properly rather than patch it. I am applying for a "
                 "thesis-based MSc starting in 2027 and would be glad to work on robust ASR for code-switched African "
                 "speech in your group. Are you taking new students for that intake?\n\nBest regards,")
    r = _draft(pid, conn, body=one_block)
    assert not r["saved"] and any("paragraph" in e for e in r["errors"])


def test_earlier_exports_count_toward_university_cap(conn):
    pid, _ = _profiled(conn)
    assert _draft(pid, conn)["saved"]
    conftest.PAGES["https://cs.x.edu/~jdoe"] = "<p>Email: jdoe [at] cs [dot] toronto [dot] edu</p>" + "x" * 4000
    assert store.verify_emails(conn)["confirmed"] == 1
    uid = store.get_professor(conn, pid)["university_id"]
    conn.execute("INSERT INTO professors (university_id, full_name, name_key, status, created_at, updated_at) "
                 "VALUES (?, 'Earlier Person', 'earlier person', 'exported', 'x', 'x')", (uid,))
    assert export.rows(conn, max_per_university=1) == []
    assert len(export.rows(conn, max_per_university=1, count_prior_exports=False)) == 1
    assert len(export.rows(conn, max_per_university=2)) == 1
