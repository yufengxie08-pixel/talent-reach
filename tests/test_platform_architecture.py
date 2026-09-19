import pytest

from talent_reach.models import TalentProfile
from talent_reach.normalization import profile_from_markdown, visible_emails
from talent_reach.platforms.aboutme import canonical_url as aboutme_url
from talent_reach.platforms.quora import _parse_quora_markdown, canonical_url as quora_url
from talent_reach.platforms.wellfound import _is_access_gate, _parse_wellfound_markdown
from talent_reach.resolver import compare_profiles, resolve_profiles


ABOUTME = """
# Yassir Elrayah on about.me
# Yassir Elrayah
## Data Scientist in Detroit, MI
-   Work
    -   General Motors
-   Education
    -   PhD, Eastern Michigan University
Mastodon @person@example.social
Email person [at] example [dot] org
"""


WELLFOUND = """
# Patrick Goodwill
Experience
[![Magnetic Insight](https://example/image.png)](https://wellfound.com/company/magnetic-insight)
[Magnetic Insight](https://wellfound.com/company/magnetic-insight)
Founder, Chief Technical Officer
Education
![University logo](https://example/logo.png)
University Of California, Berkeley · 2010
PhD, Bioengineering
Stanford University · 2004
MS, Electrical Engineering
"""


def test_platforms_have_distinct_canonical_urls():
    assert aboutme_url("ada") == "https://about.me/ada"
    assert quora_url("Ada-Lovelace") == "https://www.quora.com/profile/Ada-Lovelace"


def test_aboutme_rendered_profile_is_normalized():
    profile = profile_from_markdown(ABOUTME, "https://about.me/yassir", "aboutme")
    assert profile.name == "Yassir Elrayah"
    assert profile.headline == "Data Scientist in Detroit, MI"
    assert profile.education == ["PhD, Eastern Michigan University"]
    assert [item.value for item in profile.contacts] == ["person@example.org"]


@pytest.mark.asyncio
async def test_aboutme_location_only_heading_and_specialties(monkeypatch):
    from talent_reach.platforms import aboutme

    async def fake_read(*args, **kwargs):
        return {
            "status": "ok",
            "platform": "aboutme",
            "profile_url": "https://about.me/ada",
            "headline": "Boston, Massachusetts, United States",
            "skills": [],
            "evidence": [],
            "raw_summary": "Specialties: Robotics, Machine Learning",
        }

    monkeypatch.setattr(aboutme, "read_with_routes", fake_read)
    profile = await aboutme.read_profile("ada")
    assert profile["headline"] is None
    assert profile["location"] == "Boston, Massachusetts, United States"
    assert profile["skills"] == ["Robotics", "Machine Learning"]


def test_mastodon_handle_is_not_email():
    assert visible_emails("Mastodon @ada@example.social") == []


def test_wellfound_parser_extracts_platform_sections():
    parsed = _parse_wellfound_markdown(WELLFOUND, "https://wellfound.com/p/patrick")
    assert parsed["name"] == "Patrick Goodwill"
    assert parsed["current_org"] == "Magnetic Insight"
    assert "PhD, Bioengineering" in parsed["education"]


def test_wellfound_access_shell_is_detected():
    assert _is_access_gate("WE VALUE YOUR PRIVACY\nManage choices Agree & Proceed")
    assert _is_access_gate("Please log in to view more information about Patrick")


def test_name_only_does_not_auto_merge():
    left = TalentProfile(platform="linkedin", profile_url="https://linkedin.com/in/ada", name="Ada Example").as_dict()
    right = TalentProfile(platform="facebook", profile_url="https://facebook.com/ada", name="Ada Example").as_dict()
    result = compare_profiles(left, right)
    assert result["decision"] == "insufficient_evidence"
    assert result["score"] == 0.2


def test_public_email_can_support_identity_merge():
    left = TalentProfile(
        platform="aboutme",
        profile_url="https://about.me/ada",
        name="Ada Example",
        contacts=[{
            "kind": "email", "value": "ada@example.org", "source_url": "https://about.me/ada",
            "owner_name": "Ada Example", "owner_role": "candidate", "ownership_confidence": 1.0,
        }],
    ).as_dict()
    right = TalentProfile(
        platform="personal_site",
        profile_url="https://example.org",
        name="Ada Example",
        contacts=[{
            "kind": "email", "value": "ada@example.org", "source_url": "https://example.org",
            "owner_name": "Ada Example", "owner_role": "candidate", "ownership_confidence": 1.0,
        }],
    ).as_dict()
    resolved = resolve_profiles("Ada Example", [left, right])
    assert len(resolved["confirmed_profile_urls"]) == 2
    assert resolved["nationality"] == {"value": None, "reason": "not inferred"}


def test_direct_profile_link_can_support_identity_merge():
    left = TalentProfile(
        platform="github",
        profile_url="https://github.com/ada",
        name="Ada Example",
        links=["https://ada.example"],
    ).as_dict()
    right = TalentProfile(
        platform="personal_site",
        profile_url="https://ada.example/",
        name="Ada Example",
    ).as_dict()
    result = resolve_profiles("Ada Example", [left, right])
    assert result["comparisons"][0]["decision"] == "same_person_likely"
    assert len(result["confirmed_profile_urls"]) == 2


def test_candidate_name_mismatch_blocks_auto_confirmation():
    left = TalentProfile(
        platform="github",
        profile_url="https://github.com/ada",
        name="Ada Example",
        links=["https://ada.example"],
    ).as_dict()
    right = TalentProfile(
        platform="personal_site",
        profile_url="https://ada.example/",
        name="Ada Example",
    ).as_dict()
    result = resolve_profiles("Grace Example", [left, right])
    assert result["confirmed_profile_urls"] == []


def test_quora_credentials_are_platform_normalized():
    markdown = """
# Adam D'Angelo
#
Adam D'Angelo
Quora CEO
Credentials & Highlights
Worked at Facebook (company)
Studied at California Institute of Technology (Caltech)
Lives in Mountain View, CA
Knows about
[Computer Science](https://www.quora.com/topic/Computer-Science)
64 answers
"""
    parsed = _parse_quora_markdown(markdown, "https://www.quora.com/profile/Adam-DAngelo", "Adam D'Angelo")
    assert parsed["headline"] == "Quora CEO"
    assert parsed["current_org"] == "Facebook (company)"
    assert parsed["location"] == "Mountain View, CA"
    assert parsed["skills"] == ["Computer Science"]


def test_default_profile_refuses_nationality_inference():
    profile = TalentProfile(platform="test", profile_url="https://example.org")
    assert profile.sensitive_inferences["nationality"] == "not_inferred"
