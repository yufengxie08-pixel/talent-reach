import pytest

from talent_reach.connectors.public_web import extract_public_profile
from talent_reach.fetch import PublicFetchError, validate_public_url
from talent_reach.routing import platform_for_url


def test_extracts_only_visible_public_email_and_jsonld():
    html = """
    <html><head><title>Ada Example</title>
    <script type="application/ld+json">{"@type":"Person","name":"Ada Example","jobTitle":"Engineer"}</script>
    <script>const hidden = "hidden@example.com";</script></head>
    <body><p>Contact ada@example.org</p><a href="mailto:work@example.edu">Email</a>
    <p>Mastodon: @ada@example.social</p></body></html>
    """
    result = extract_public_profile(html, "https://example.org/ada")
    assert result["name"] == "Ada Example"
    assert result["headline"] == "Engineer"
    assert result["emails"] == ["ada@example.org", "work@example.edu"]
    assert "hidden@example.com" not in result["emails"]
    assert "ada@example.social" not in result["emails"]


@pytest.mark.asyncio
async def test_rejects_private_network_urls():
    with pytest.raises(PublicFetchError) as exc:
        await validate_public_url("http://127.0.0.1/private")
    assert exc.value.code == "private_network"


def test_routes_known_platforms():
    assert platform_for_url("https://about.me/example") == "aboutme"
    assert platform_for_url("https://www.quora.com/profile/Example") == "quora"
    assert platform_for_url("https://wellfound.com/u/example") == "wellfound"
    assert platform_for_url("https://example.org/me") == "personal"
