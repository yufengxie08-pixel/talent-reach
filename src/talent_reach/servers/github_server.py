from talent_reach.platforms import github_public
from talent_reach.servers.common import make_server

mcp = make_server("GitHub Public Talent")

@mcp.tool
async def search_github_people(query: str, location: str | None = None, limit: int = 10) -> dict:
    """Search GitHub users through the public REST API."""
    return await github_public.search_profiles(query, location, limit)

@mcp.tool
async def read_github_profile(username: str, repo_limit: int = 12) -> dict:
    """Read public profile and recent-repository language evidence, never commit emails."""
    return await github_public.read_profile(username, repo_limit)

@mcp.tool
async def github_public_doctor() -> dict:
    """Probe the GitHub public REST backend."""
    return await github_public.doctor()

def main() -> None:
    mcp.run()

