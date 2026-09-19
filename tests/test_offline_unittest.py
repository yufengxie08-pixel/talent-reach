"""Dependency-free regression suite runnable with the installed application Python."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from talent_reach.batch import qualify_batch, results_to_csv
from talent_reach.connectors.public_web import _crawl_candidate_allowed, extract_public_profile
from talent_reach.fetch import PublicFetchError, validate_public_url
from talent_reach.models import TalentProfile
from talent_reach.normalization import visible_emails
from talent_reach.qualifier import merge_candidate_profiles, qualify_candidate
from talent_reach.rankings import (
    get_company_membership,
    get_university_rank,
    ranking_doctor,
    validate_ranking_snapshot,
)
from talent_reach.resolver import compare_profiles
from talent_reach.resume_parser import extract_current_employment, extract_education


class OfflineRegressionTests(unittest.TestCase):
    def test_word_obfuscation(self):
        self.assertEqual(
            visible_emails("cbfinn at cs dot stanford dot edu"),
            ["cbfinn@cs.stanford.edu"],
        )

    def test_mastodon_is_not_email(self):
        self.assertEqual(visible_emails("Mastodon @ada@example.social"), [])

    def test_scripts_do_not_leak_hidden_email(self):
        result = extract_public_profile(
            '<title>Ada Example</title><script>"hidden@example.com"</script><p>ada@example.edu</p>',
            "https://example.edu/ada",
        )
        self.assertEqual(result["emails"], ["ada@example.edu"])

    def test_candidate_and_assistant_ownership(self):
        result = extract_public_profile(
            "<title>Ada Example</title><p>Email: ada@example.edu</p>"
            "<p>Administrative Assistant: helper@example.edu</p>",
            "https://example.edu/ada",
        )
        values = {item["value"]: item for item in result["email_mentions"]}
        self.assertEqual(values["ada@example.edu"]["owner_role"], "candidate")
        self.assertEqual(values["helper@example.edu"]["owner_role"], "assistant")
        self.assertEqual(result["candidate_emails"], ["ada@example.edu"])

    def test_directory_scope(self):
        start = "https://example.edu/people-finder?page=detail&id=1"
        self.assertFalse(
            _crawl_candidate_allowed(
                start, {"url": "https://example.edu/people-finder", "text": "People Finder"}
            )
        )
        self.assertFalse(
            _crawl_candidate_allowed(
                start, {"url": "https://example.edu/contact-us", "text": "Contact Us"}
            )
        )

    def test_private_url(self):
        with self.assertRaises(PublicFetchError):
            asyncio.run(validate_public_url("http://127.0.0.1/private"))

    def test_resume_extraction(self):
        text = (
            "I am an Assistant Professor of Computer Science at Stanford University. "
            "I finished my PhD at MIT, advised by Bill Freeman."
        )
        self.assertEqual(extract_education(text, "x")[0].institution, "MIT")
        self.assertEqual(
            extract_current_employment(text, "x")[0].organization, "Stanford University"
        )

    def test_dotted_phd_sentence(self):
        text = "She completed her Ph.D. in computer science at UC Berkeley in 2018."
        record = extract_education(text, "x")[0]
        self.assertEqual(record.institution, "UC Berkeley")
        self.assertEqual(record.year, 2018)

    def test_multiple_degrees_are_preserved(self):
        text = (
            "She earned a B.S. in Electrical Engineering at MIT in 2012, "
            "an M.S. in Computer Science at Stanford University in 2014, "
            "and a Ph.D. in Computer Science at UC Berkeley in 2019."
        )
        records = extract_education(text, "x")
        self.assertEqual([item.degree for item in records], ["Bachelor's", "Master's", "PhD"])
        self.assertEqual([item.institution for item in records], ["MIT", "Stanford University", "UC Berkeley"])

    def test_rank_alias_and_edition(self):
        result = get_university_rank("UC Berkeley", "2027")
        self.assertEqual(result["rank"], 20)
        self.assertEqual(result["edition"], "2027")
        self.assertEqual(get_university_rank("UC Berkeley", "2026")["status"], "unavailable")

    def test_unknown_rank_never_guessed(self):
        self.assertEqual(
            get_university_rank("Unknown Similar University")["status"], "unresolved"
        )

    def test_fortune_unavailable_is_explicit(self):
        old = os.environ.pop("TALENT_REACH_FORTUNE_DATA", None)
        try:
            self.assertEqual(get_company_membership("Example Corp")["status"], "unavailable")
        finally:
            if old is not None:
                os.environ["TALENT_REACH_FORTUNE_DATA"] = old

    def test_user_supplied_fortune_snapshot(self):
        payload = {
            "edition": "2026",
            "coverage": "test_snapshot",
            "source_url": "https://fortune.com/ranking/global500/",
            "organizations": [{
                "canonical_name": "Example Corporation",
                "aliases": ["Example Corp"],
                "domains": ["example.com"],
                "type": "company",
                "memberships": [{
                    "list": "fortune_global_500", "year": 2026, "rank": 123,
                    "source_url": "https://fortune.com/ranking/global500/",
                }],
            }],
        }
        old = os.environ.get("TALENT_REACH_FORTUNE_DATA")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fortune.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            os.environ["TALENT_REACH_FORTUNE_DATA"] = str(path)
            try:
                result = get_company_membership("Example Corp", year=2026)
                self.assertEqual(result["status"], "ok")
                self.assertTrue(result["is_member"])
            finally:
                if old is None:
                    os.environ.pop("TALENT_REACH_FORTUNE_DATA", None)
                else:
                    os.environ["TALENT_REACH_FORTUNE_DATA"] = old

    def test_invalid_snapshot_is_rejected(self):
        validation = validate_ranking_snapshot({"organizations": []}, "qs")
        self.assertFalse(validation["valid"])
        self.assertIn("edition is required.", validation["errors"])

    def test_invalid_configured_qs_never_silently_falls_back(self):
        old = os.environ.get("TALENT_REACH_QS_DATA")
        os.environ["TALENT_REACH_QS_DATA"] = "/path/that/does/not/exist.json"
        try:
            self.assertEqual(get_university_rank("MIT")["status"], "config_error")
        finally:
            if old is None:
                os.environ.pop("TALENT_REACH_QS_DATA", None)
            else:
                os.environ["TALENT_REACH_QS_DATA"] = old

    def test_ranking_doctor_reports_subset(self):
        self.assertEqual(ranking_doctor()["qs"]["coverage"], "verified_subset_not_full_ranking")

    def test_name_only_not_merged(self):
        left = TalentProfile(platform="a", profile_url="https://a.example", name="Ada Example").as_dict()
        right = TalentProfile(platform="b", profile_url="https://b.example", name="Ada Example").as_dict()
        self.assertEqual(compare_profiles(left, right)["decision"], "insufficient_evidence")

    def test_qualifier_all_pass(self):
        result = qualify_candidate(_jiajun_profile())
        self.assertEqual(result["decision"], "eligible")
        self.assertTrue(result["eligible"])

    def test_ambiguous_email_stays_review(self):
        profile = _jiajun_profile()
        profile["contacts"][0]["owner_role"] = "administrator"
        self.assertEqual(qualify_candidate(profile)["checks"]["candidate_email"]["status"], "review")

    def test_merge_rejects_wrong_person(self):
        accepted = _jiajun_profile()
        rejected = {**accepted, "name": "Grace Hopper", "profile_url": "https://wrong.example"}
        merged = merge_candidate_profiles("Jiajun Wu", [accepted, rejected])
        self.assertEqual(merged["source_profile_urls"], [accepted["profile_url"]])
        self.assertEqual(len(merged["rejected_profiles"]), 1)

    def test_batch_isolates_invalid_candidate(self):
        result = asyncio.run(qualify_batch([
            {"candidate_name": "Jiajun Wu", "profiles": [_jiajun_profile()]},
            {"candidate_name": "", "profiles": [_jiajun_profile()]},
        ]))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["summary"], {
            "total": 2, "eligible": 1, "ineligible": 0, "review": 0, "error": 1,
        })

    def test_csv_export_blocks_formula_injection(self):
        result = {
            "results": [{
                "input_index": 0,
                "candidate_name": "=HYPERLINK(\"bad\")",
                "merged_profile": {},
                "qualification": {"decision": "review", "eligible": False, "checks": {}, "unresolved": []},
            }]
        }
        csv_text = results_to_csv(result)
        self.assertIn("'=HYPERLINK", csv_text)


def _jiajun_profile():
    return {
        "status": "ok",
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
        "employment_records": [],
        "education": [],
        "skills": ["machine learning", "robotics"],
        "links": [],
        "evidence": [],
        "contacts": [{
            "kind": "email", "value": "jiajunwu@cs.stanford.edu",
            "source_url": "https://jiajunwu.com/", "visibility": "explicit_public",
            "owner_role": "candidate", "ownership_confidence": 0.98,
        }],
    }


if __name__ == "__main__":
    unittest.main(verbosity=2)
