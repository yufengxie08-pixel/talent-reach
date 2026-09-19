import json

from talent_reach.batch import qualify_batch, results_to_csv
from talent_reach.connectors.public_web import _crawl_candidate_allowed, extract_public_profile
from talent_reach.normalization import visible_emails
from talent_reach.qualifier import qualify_candidate
from talent_reach.rankings import get_company_membership, get_university_rank, validate_ranking_snapshot
from talent_reach.resume_parser import extract_current_employment, extract_education


def test_word_obfuscated_email_is_normalized_without_guessing():
    assert visible_emails("cbfinn at cs dot stanford dot edu") == ["cbfinn@cs.stanford.edu"]


def test_candidate_and_assistant_email_are_attributed_separately():
    html = """
    <title>Ada Example</title>
    <p>Email: ada@example.edu</p>
    <p>Administrative Assistant: helper@example.edu</p>
    """
    result = extract_public_profile(html, "https://example.edu/ada")
    by_email = {item["value"]: item for item in result["email_mentions"]}
    assert by_email["ada@example.edu"]["owner_role"] == "candidate"
    assert by_email["helper@example.edu"]["owner_role"] == "assistant"
    assert result["candidate_emails"] == ["ada@example.edu"]


def test_directory_detail_does_not_crawl_back_to_list_or_contact():
    start = "https://example.edu/people-finder?page=detail&id=1"
    assert not _crawl_candidate_allowed(
        start, {"url": "https://example.edu/people-finder", "text": "People Finder"}
    )
    assert not _crawl_candidate_allowed(
        start, {"url": "https://example.edu/contact-us", "text": "Contact Us"}
    )


def test_resume_parser_extracts_doctorate_and_current_employer():
    text = (
        "I am an Assistant Professor of Computer Science at Stanford University. "
        "I finished my PhD at MIT, advised by Bill Freeman."
    )
    education = extract_education(text, "https://example.edu")
    employment = extract_current_employment(text, "https://example.edu")
    assert education[0].institution == "MIT"
    assert employment[0].organization == "Stanford University"


def test_resume_parser_keeps_bachelor_master_and_doctorate_history():
    text = (
        "She earned a B.S. in Electrical Engineering at MIT in 2012, "
        "an M.S. in Computer Science at Stanford University in 2014, "
        "and a Ph.D. in Computer Science at UC Berkeley in 2019."
    )
    education = extract_education(text, "https://example.edu")
    assert [item.degree for item in education] == ["Bachelor's", "Master's", "PhD"]
    assert [item.institution for item in education] == ["MIT", "Stanford University", "UC Berkeley"]


def test_qs_aliases_are_exact_and_versioned():
    result = get_university_rank("UC Berkeley", "2027")
    assert result["rank"] == 20
    assert result["edition"] == "2027"
    assert get_university_rank("Unknown Similar University", "2027")["status"] == "unresolved"


def test_fortune_is_explicitly_unavailable_without_verified_snapshot(monkeypatch):
    monkeypatch.delenv("TALENT_REACH_FORTUNE_DATA", raising=False)
    assert get_company_membership("Example Corp")["status"] == "unavailable"


def test_user_supplied_fortune_snapshot_is_used(monkeypatch, tmp_path):
    path = tmp_path / "fortune.json"
    path.write_text(
        '{"edition":"2026","coverage":"test_snapshot",'
        '"source_url":"https://fortune.com/ranking/global500/",'
        '"organizations":[{"canonical_name":"Example Corporation",'
        '"aliases":["Example Corp"],"domains":["example.com"],"type":"company",'
        '"memberships":[{"list":"fortune_global_500","year":2026,"rank":123,'
        '"source_url":"https://fortune.com/ranking/global500/"}]}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("TALENT_REACH_FORTUNE_DATA", str(path))
    result = get_company_membership("Example Corp", year=2026)
    assert result["status"] == "ok"
    assert result["is_member"] is True


def test_invalid_ranking_snapshot_reports_actionable_errors():
    result = validate_ranking_snapshot({"organizations": []}, "qs")
    assert result["valid"] is False
    assert "edition is required." in result["errors"]


def test_hard_condition_qualifier_passes_only_with_all_evidence():
    profile = {
        "name": "Jiajun Wu",
        "profile_url": "https://jiajunwu.com/",
        "headline": "Assistant Professor of Computer Science",
        "current_org": "Stanford University",
        "raw_summary": "computer vision machine learning robotics",
        "education_records": [{
            "degree": "PhD", "institution": "MIT", "field": "EECS", "year": 2020,
            "source_url": "https://jiajunwu.com/", "source_text": "I finished my PhD at MIT",
            "confidence": "high",
        }],
        "contacts": [{
            "kind": "email", "value": "jiajunwu@cs.stanford.edu",
            "source_url": "https://jiajunwu.com/", "visibility": "explicit_public",
            "owner_role": "candidate", "ownership_confidence": 0.98,
        }],
    }
    result = qualify_candidate(profile)
    assert result["decision"] == "eligible"
    assert all(item["status"] == "pass" for item in result["checks"].values())


def test_ambiguous_email_or_unknown_rank_stays_review():
    profile = {
        "name": "Ada Example",
        "profile_url": "https://example.edu/ada",
        "headline": "Computer Scientist",
        "current_org": "Unknown Lab",
        "education_records": [{
            "degree": "PhD", "institution": "Unknown Similar University", "field": "Computer Science",
            "source_url": "https://example.edu/ada", "source_text": "PhD in Computer Science",
        }],
        "contacts": [{
            "kind": "email", "value": "admin@example.edu", "source_url": "https://example.edu/ada",
            "visibility": "explicit_public", "owner_role": "administrator", "ownership_confidence": 0.9,
        }],
    }
    result = qualify_candidate(profile)
    assert result["decision"] == "review"
    assert result["eligible"] is False
    assert result["checks"]["candidate_email"]["status"] == "review"


async def test_batch_failure_isolation_and_csv_formula_safety():
    profile = {
        "status": "ok",
        "name": "Jiajun Wu",
        "profile_url": "https://jiajunwu.com/",
        "headline": "Assistant Professor of Computer Science",
        "current_org": "Stanford University",
        "raw_summary": "machine learning robotics",
        "education_records": [{
            "degree": "PhD", "institution": "MIT", "field": "EECS",
            "source_url": "https://jiajunwu.com/", "source_text": "PhD at MIT",
        }],
        "contacts": [{
            "kind": "email", "value": "jiajunwu@cs.stanford.edu",
            "source_url": "https://jiajunwu.com/", "visibility": "explicit_public",
            "owner_role": "candidate", "ownership_confidence": 0.98,
        }],
    }
    result = await qualify_batch([
        {"candidate_name": "Jiajun Wu", "profiles": [profile]},
        {"candidate_name": "", "profiles": [profile]},
    ])
    assert result["summary"]["eligible"] == 1
    assert result["summary"]["error"] == 1
    malicious = json.loads(json.dumps(result))
    malicious["results"][0]["candidate_name"] = "=HYPERLINK(\"bad\")"
    assert "'=HYPERLINK" in results_to_csv(malicious)
