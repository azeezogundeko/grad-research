from gradlead.normalize import deobfuscate, first_name, last_name, name_key, same_person, seniority, university_key


def test_name_key_strips_honorifics_and_accents():
    assert name_key("Prof. Dr. José  Pérez-Ruiz") == "jose perez ruiz"
    assert name_key("Assoc. Prof. Jane Doe") == "jane doe"


def test_university_key():
    assert university_key("The University of Edinburgh") == university_key("University Edinburgh")


def test_same_person_handles_initials_and_order():
    assert same_person("Jane Doe", "J. Doe")
    assert same_person("Wei Wang", "Wang Wei")
    assert not same_person("Jane Doe", "Jane Smith")


def test_names():
    assert first_name("Prof. Jane Doe") == "Jane"
    assert last_name("Jane van der Berg") == "Berg"


def test_seniority_order():
    assert seniority("Assistant Professor") == "early"
    assert seniority("Associate Professor of CS") == "mid"
    assert seniority("Senior Lecturer") == "mid"
    assert seniority("Lecturer in AI") == "early"
    assert seniority("Professor and Chair") == "senior"
    assert seniority("Professor Emeritus") == "emeritus"
    assert seniority("Research Scientist") == "non_supervisor"
    assert seniority(None) == "unknown"


def test_crawl_find_emails():
    from gradlead.crawl import find_emails
    assert find_emails("Contact: jdoe [at] cs [dot] uni [dot] edu. Office 3.14") == ["jdoe@cs.uni.edu"]


def test_deobfuscate():
    assert "jdoe@cs.uni.edu" in deobfuscate("Email: jdoe [at] cs [dot] uni [dot] edu")
    assert "jdoe@uni.edu" in deobfuscate("jdoe(at)uni.edu")
    assert "jdoe@cs.uni.edu" in deobfuscate("jdoe at cs dot uni dot edu")
    assert "jdoe@uni.edu" in deobfuscate("jdoe{at}uni{dot}edu")


def test_same_person_rejects_different_given_names():
    assert not same_person("Hongsheng Li", "Hongyang Li")
    assert same_person("H. Li", "Hongsheng Li")
    assert same_person("Kam-Fai Wong", "Kam Fai Wong")
