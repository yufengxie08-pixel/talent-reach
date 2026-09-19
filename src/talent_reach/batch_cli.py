from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from talent_reach.batch import qualify_batch, results_to_csv


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch public-talent qualification")
    parser.add_argument("--input", required=True, help="JSON file containing a jobs array")
    parser.add_argument("--output", required=True, help="Destination CSV file")
    parser.add_argument("--json-output", help="Optional full evidence JSON destination")
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument("--phd-qs-max", type=int, default=100)
    parser.add_argument("--employer-qs-max", type=int, default=200)
    parser.add_argument("--qs-edition", default="2027")
    parser.add_argument("--fortune-year", type=int)
    parser.add_argument("--no-fortune", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
    if not isinstance(jobs, list):
        raise SystemExit("Input JSON must be an array or an object containing a jobs array.")
    result = asyncio.run(
        qualify_batch(
            jobs,
            max_concurrency=args.max_concurrency,
            phd_qs_max=args.phd_qs_max,
            employer_qs_max=args.employer_qs_max,
            qs_edition=args.qs_edition,
            allow_fortune_global_500=not args.no_fortune,
            fortune_year=args.fortune_year,
            include_research=bool(args.json_output),
        )
    )
    Path(args.output).write_text(results_to_csv(result), encoding="utf-8-sig")
    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(result.get("summary", {}), ensure_ascii=False))


if __name__ == "__main__":
    main()
