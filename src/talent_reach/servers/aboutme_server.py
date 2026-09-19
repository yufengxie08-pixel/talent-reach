from talent_reach.platforms import aboutme
from talent_reach.servers.common import make_server

mcp = make_server("About.me Talent")

@mcp.tool
async def search_aboutme_profiles(query: str, location: str | None = None, limit: int = 10) -> dict:
    """Discover About.me profiles using site-restricted browser search."""
    return await aboutme.search_profiles(query, location, limit)

@mcp.tool
async def read_aboutme_profile(handle_or_url: str) -> dict:
    """Read one About.me profile into the normalized talent schema."""
    return await aboutme.read_profile(handle_or_url)

@mcp.tool
def aboutme_doctor() -> dict:
    """Probe the About.me backend and browser bridge."""
    return aboutme.doctor()

def main() -> None:
    mcp.run()

