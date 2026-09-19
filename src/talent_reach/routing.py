"""Internal URL classification for normalized low-level fetch results."""

from __future__ import annotations

from urllib.parse import urlparse


def platform_for_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    if host == "facebook.com" or host.endswith(".facebook.com"):
        return "facebook"
    if host in {"x.com", "twitter.com"} or host.endswith((".x.com", ".twitter.com")):
        return "twitter"
    if host == "github.com" or host.endswith(".github.com"):
        return "github"
    if host in {"stackoverflow.com", "stackexchange.com"} or host.endswith(
        (".stackoverflow.com", ".stackexchange.com")
    ):
        return "stackoverflow"
    if host == "about.me" or host.endswith(".about.me"):
        return "aboutme"
    if host == "quora.com" or host.endswith(".quora.com"):
        return "quora"
    if host in {"wellfound.com", "angel.co"} or host.endswith(
        (".wellfound.com", ".angel.co")
    ):
        return "wellfound"
    return "personal"
