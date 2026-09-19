import asyncio

from talent_reach.platforms import aboutme, github_public, personal_site, quora, stackexchange, wellfound
from talent_reach.resolver import enrich_urls, resolve_profiles
from talent_reach.rankings import ranking_doctor
from talent_reach.servers.common import make_server

mcp = make_server("Talent Identity Resolver")

@mcp.tool
def resolve_candidate_profiles(candidate_name: str, profiles: list[dict]) -> dict:
    """Resolve normalized platform profiles with explainable conservative scoring."""
    return resolve_profiles(candidate_name, profiles)

@mcp.tool
async def enrich_candidate_urls(candidate_name: str, urls: list[str]) -> dict:
    """Dispatch up to ten URLs to their platform MCP logic, then resolve identity."""
    return await enrich_urls(candidate_name, urls)

@mcp.tool
async def talent_platforms_doctor(check_network: bool = True) -> dict:
    """Run platform-level health checks and report each active backend."""
    checks = await asyncio.gather(
        github_public.doctor(),
        stackexchange.doctor(),
        wellfound.doctor(check_network),
    )
    return {
        "status": "ok",
        "platforms": {
            "aboutme": aboutme.doctor(),
            "quora": quora.doctor(),
            "wellfound": checks[2],
            "stackoverflow": checks[1],
            "github": checks[0],
            "personal_site": personal_site.doctor(),
            "organization_ranking": ranking_doctor(),
        },
    }

def main() -> None:
    mcp.run()
