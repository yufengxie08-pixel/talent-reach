from talent_reach.qualifier import merge_candidate_profiles, qualifier_doctor, qualify_candidate
from talent_reach.resolver import enrich_urls
from talent_reach.servers.common import make_server

mcp = make_server("Talent Hard-Condition Qualifier")


@mcp.tool
def qualify_talent_candidate(
    profile: dict,
    phd_qs_max: int = 100,
    employer_qs_max: int = 200,
    qs_edition: str = "2027",
    allow_fortune_global_500: bool = True,
    fortune_year: int | None = None,
    require_overseas_phd: bool = True,
    require_public_candidate_email: bool = True,
) -> dict:
    """Apply deterministic doctorate, ranking, STEM, employer, and email checks."""
    return qualify_candidate(
        profile,
        phd_qs_max=phd_qs_max,
        employer_qs_max=employer_qs_max,
        qs_edition=qs_edition,
        allow_fortune_global_500=allow_fortune_global_500,
        fortune_year=fortune_year,
        require_overseas_phd=require_overseas_phd,
        require_public_candidate_email=require_public_candidate_email,
    )


@mcp.tool
async def research_and_qualify_candidate(
    candidate_name: str,
    urls: list[str],
    phd_qs_max: int = 100,
    employer_qs_max: int = 200,
    qs_edition: str = "2027",
    allow_fortune_global_500: bool = True,
    fortune_year: int | None = None,
) -> dict:
    """Read public URLs, conservatively merge matching profiles, and apply every hard condition."""
    research = await enrich_urls(candidate_name, urls)
    merged = merge_candidate_profiles(candidate_name, research.get("profiles", []))
    qualification = qualify_candidate(
        merged,
        phd_qs_max=phd_qs_max,
        employer_qs_max=employer_qs_max,
        qs_edition=qs_edition,
        allow_fortune_global_500=allow_fortune_global_500,
        fortune_year=fortune_year,
    )
    return {"status": "ok", "research": research, "merged_profile": merged, "qualification": qualification}


@mcp.tool
def talent_qualifier_doctor() -> dict:
    """Report rule policy and installed ranking evidence coverage."""
    return qualifier_doctor()


def main() -> None:
    mcp.run()
