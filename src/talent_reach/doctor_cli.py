from __future__ import annotations

import asyncio
import json

from talent_reach.batch import batch_doctor
from talent_reach.platforms import aboutme, github_public, personal_site, quora, stackexchange, wellfound
from talent_reach.qualifier import qualifier_doctor
from talent_reach.rankings import ranking_doctor


async def _run() -> dict:
    github_status, stack_status, wellfound_status = await asyncio.gather(
        github_public.doctor(), stackexchange.doctor(), wellfound.doctor(True)
    )
    return {
        "aboutme": aboutme.doctor(),
        "quora": quora.doctor(),
        "wellfound": wellfound_status,
        "stackoverflow": stack_status,
        "github": github_status,
        "personal_site": personal_site.doctor(),
        "organization_ranking": ranking_doctor(),
        "hard_condition_qualifier": qualifier_doctor(),
        "batch_qualification": batch_doctor(),
    }


def main() -> None:
    print(json.dumps(asyncio.run(_run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
