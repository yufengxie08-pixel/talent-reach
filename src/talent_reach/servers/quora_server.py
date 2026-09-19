from talent_reach.platforms import quora
from talent_reach.servers.common import make_server

mcp = make_server("Quora Talent")

@mcp.tool
async def search_quora_profiles(query: str, location: str | None = None, limit: int = 10) -> dict:
    """Discover public Quora profiles for expertise corroboration."""
    return await quora.search_profiles(query, location, limit)

@mcp.tool
async def read_quora_profile(profile_or_url: str) -> dict:
    """Read visible Quora profile content; this is not an email-enrichment source."""
    return await quora.read_profile(profile_or_url)

@mcp.tool
def quora_doctor() -> dict:
    """Probe the Quora browser-backed route."""
    return quora.doctor()

def main() -> None:
    mcp.run()

