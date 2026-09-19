from talent_reach.platforms import stackexchange
from talent_reach.servers.common import make_server

mcp = make_server("Stack Exchange Talent")

@mcp.tool
async def search_stackoverflow_people(name: str, location: str | None = None, site: str = "stackoverflow", limit: int = 30) -> dict:
    """Search public Stack Exchange users by display name and optional location."""
    return await stackexchange.search_profiles(name, location, site, limit)

@mcp.tool
async def read_stackoverflow_profile(user_id: int, site: str = "stackoverflow", tag_limit: int = 20) -> dict:
    """Read a Stack Overflow user's reputation, top tags, website, and profile."""
    return await stackexchange.read_profile(user_id, site, tag_limit)

@mcp.tool
async def stackexchange_doctor() -> dict:
    """Probe the Stack Exchange public API."""
    return await stackexchange.doctor()

def main() -> None:
    mcp.run()

