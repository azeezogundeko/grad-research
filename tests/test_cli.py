import json

from conftest import write_json

from gradlead.cli import main


def test_cli_roundtrip(conn, tmp_path, capsys):
    t = tmp_path / "targets.txt"
    t.write_text("Canada|University of Toronto|5\n", encoding="utf-8")
    assert main(["targets", "--sync", "--file", str(t)]) == 0
    assert json.loads(capsys.readouterr().out)["totals"]["to_discover"] == 5

    f = write_json(tmp_path, "p.json", [{"full_name": "Jane Doe", "title": "Assistant Professor",
                                         "source_url": "https://cs.x.edu/people"}])
    assert main(["add-profs", "1", f, "--directory-url", "https://cs.x.edu/people", "--done"]) == 0
    assert json.loads(capsys.readouterr().out)["added"] == 1
    assert main(["queue"]) == 0
    q = json.loads(capsys.readouterr().out)
    assert q[0]["full_name"] == "Jane Doe" and q[0]["region"] == "Canada"
    assert main(["show", "1", "--brief"]) == 0
    assert json.loads(capsys.readouterr().out)["funding"]["contact_first"] == "expected"
    assert main(["applicant"]) == 0
    assert "vonative" in json.loads(capsys.readouterr().out)["projects"]
    assert main(["export", "--out", str(tmp_path / "x.csv"), "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 0
    assert main(["show", "999"]) == 1
