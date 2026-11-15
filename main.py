"""Run:  python main.py --inbox data/inbox.json --profile data/creator_profile.json
Test the connection:  python main.py --check"""
import argparse
import json
from datetime import date
from pathlib import Path

from brand_deals.llm import GeminiClient
from brand_deals.loader import load_emails, load_profile
from brand_deals.pipeline import run_pipeline
from brand_deals.reporting import write_summary
from brand_deals.utils import parse_date


def main():
    ap = argparse.ArgumentParser(description="Brand deal intelligence")
    ap.add_argument("--inbox", default="data/inbox.json")
    ap.add_argument("--profile", default="data/creator_profile.json")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--today", help="Treat this date (YYYY-MM-DD) as today. Default: date of the newest email.")
    ap.add_argument("--limit", type=int, help="Only process the first N emails (for quick tests).")
    ap.add_argument("--ai-drafts", action="store_true", help="Polish reply drafts with the model (one extra call).")
    ap.add_argument("--check", action="store_true", help="Test the Gemini connection and list usable models, then exit.")
    args = ap.parse_args()

    if args.check:
        ok, message = GeminiClient().check()
        print(("OK: " if ok else "FAILED: ") + message)
        return

    emails = load_emails(args.inbox)
    if args.limit:
        emails = emails[: args.limit]
    profile = load_profile(args.profile)
    dates = [d for d in (parse_date(e.date) for e in emails) if d]
    today = parse_date(args.today) or (max(dates) if dates else date.today())

    analysis = run_pipeline(emails, profile, today, GeminiClient(), ai_drafts=args.ai_drafts)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    write_summary(analysis, out / "summary.md")
    print(f"\nDone. Wrote {out}/analysis.json and {out}/summary.md")
    print(json.dumps(analysis["stats"], indent=2))


if __name__ == "__main__":
    main()