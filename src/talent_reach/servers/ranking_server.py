from talent_reach.rankings import (
    get_company_membership,
    get_university_rank,
    ranking_doctor,
    resolve_organization,
    validate_ranking_snapshot,
)
from talent_reach.servers.common import make_server

mcp = make_server("Organization Ranking Evidence")


@mcp.tool
def resolve_ranked_organization(name: str, domain: str | None = None) -> dict:
    """Resolve an exact organization alias or domain from installed evidence snapshots."""
    return resolve_organization(name, domain)


@mcp.tool
def get_qs_university_rank(name: str, edition: str = "2027", domain: str | None = None) -> dict:
    """Return a verified QS rank and official source, never an inferred rank."""
    return get_university_rank(name, edition, domain)


@mcp.tool
def get_fortune_company_membership(
    name: str, list_name: str = "fortune_global_500", year: int | None = None
) -> dict:
    """Check a configured verified Fortune snapshot; unavailable is explicit."""
    return get_company_membership(name, list_name, year)


@mcp.tool
def organization_ranking_doctor() -> dict:
    """Report ranking editions, snapshot coverage, and Fortune configuration."""
    return ranking_doctor()


@mcp.tool
def validate_organization_snapshot(payload: dict, snapshot_kind: str) -> dict:
    """Validate a QS or Fortune JSON snapshot before configuring it for production use."""
    return validate_ranking_snapshot(payload, snapshot_kind)


def main() -> None:
    mcp.run()
