from talent_reach.platforms import personal_site
from talent_reach.servers.common import make_server

mcp = make_server("Personal Site Talent")

@mcp.tool
async def read_personal_site(url: str, max_pages: int = 5, include_cv_pdf: bool = True) -> dict:
    """Read bounded same-origin About/Contact pages and linked public CV PDFs."""
    return await personal_site.read_site(url, max_pages, include_cv_pdf)


@mcp.tool
async def read_public_cv_pdf(url: str, candidate_name: str | None = None) -> dict:
    """Read a directly supplied public CV PDF with bounded size and page count."""
    return await personal_site.read_cv_pdf(url, candidate_name)

@mcp.tool
def personal_site_doctor() -> dict:
    """Report crawler limits and SSRF protections."""
    return personal_site.doctor()

def main() -> None:
    mcp.run()
