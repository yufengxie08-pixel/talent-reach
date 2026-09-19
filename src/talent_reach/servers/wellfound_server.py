from talent_reach.platforms import wellfound
from talent_reach.servers.common import make_server

mcp = make_server("Wellfound Talent")

@mcp.tool
async def search_wellfound_people(query: str, location: str | None = None, limit: int = 10) -> dict:
    """Discover public Wellfound people pages using site-restricted search."""
    return await wellfound.search_people(query, location, limit)

@mcp.tool
async def read_wellfound_profile(profile_or_url: str) -> dict:
    """Read public Wellfound profile content without recruiter-only access."""
    return await wellfound.read_profile(profile_or_url)

@mcp.tool
async def wellfound_doctor(check_network: bool = False) -> dict:
    """Probe Wellfound direct and browser-backed routes."""
    return await wellfound.doctor(check_network)

def main() -> None:
    mcp.run()

