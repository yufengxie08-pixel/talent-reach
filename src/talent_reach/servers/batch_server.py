from talent_reach.batch import batch_doctor, qualify_batch, results_to_csv
from talent_reach.servers.common import make_server

mcp = make_server("Talent Batch Qualification")


@mcp.tool
async def qualify_talent_batch(
    jobs: list[dict],
    max_concurrency: int = 3,
    phd_qs_max: int = 100,
    employer_qs_max: int = 200,
    qs_edition: str = "2027",
    allow_fortune_global_500: bool = True,
    fortune_year: int | None = None,
    include_research: bool = False,
) -> dict:
    """Qualify up to 100 candidates with bounded concurrency and isolated failures."""
    return await qualify_batch(
        jobs,
        max_concurrency=max_concurrency,
        phd_qs_max=phd_qs_max,
        employer_qs_max=employer_qs_max,
        qs_edition=qs_edition,
        allow_fortune_global_500=allow_fortune_global_500,
        fortune_year=fortune_year,
        include_research=include_research,
    )


@mcp.tool
def qualification_results_to_csv(batch_result: dict) -> dict:
    """Render batch results as UTF-8 CSV with spreadsheet formula-injection protection."""
    csv_text = results_to_csv(batch_result)
    return {
        "status": "ok",
        "content_type": "text/csv; charset=utf-8",
        "row_count": len(batch_result.get("results", [])),
        "csv": csv_text,
    }


@mcp.tool
def talent_batch_doctor() -> dict:
    """Report batch safety limits, accepted inputs, and export protections."""
    return batch_doctor()


def main() -> None:
    mcp.run()
