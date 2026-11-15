from datetime import date

from .utils import parse_date

SECTIONS = [
    ("Needs your attention today", {"accept", "negotiate", "ask_for_details"}),
    ("Not a fit (decline)", {"decline"}),
    ("Suspicious: do not engage", {"ignore_or_report"}),
]
ACTION_TEXT = {"accept": "Accept", "negotiate": "Negotiate", "ask_for_details": "Ask for details",
               "decline": "Decline", "ignore_or_report": "Ignore / report"}


def _sort_key(d):
    dl = parse_date(d.get("deadline")) or date.max
    return (dl, d["deal_id"])


def build_summary(analysis: dict) -> str:
    deals = analysis["deals"]
    s = analysis["stats"]
    lines = [f"# Brand deal summary for {analysis['creator']} ({analysis['as_of']})", "",
             f"{s['emails']} emails turned into {s['deals']} deals. {s['needs_attention']} need a reply from you.", ""]
    for title, actions in SECTIONS:
        items = sorted([d for d in deals if d["recommended_action"] in actions], key=_sort_key)
        if not items:
            continue
        lines += [f"## {title}", ""]
        for d in items:
            lines.append(f"### {d['headline']}  ({d['deal_id']}, emails {', '.join(d['email_ids'])})")
            lines.append(f"- **Do this:** {ACTION_TEXT[d['recommended_action']]}")
            if d["deadline"]:
                lines.append(f"- **Deadline:** {d['deadline']}")
            for f in d["risk_flags"]:
                lines.append(f"- **{f['severity'].upper()} risk:** {f['reason']}")
            if d["missing_info"] and d["recommended_action"] == "ask_for_details":
                lines.append(f"- **Missing:** {', '.join(d['missing_info'])}")
            if d["reply_draft"]:
                body = d["reply_draft"]["body"].strip().replace("\n", "\n> ")
                lines += ["", "> " + body]
            lines.append("")
    spam = [e for e in analysis["emails"] if e["category"] == "spam"]
    if spam:
        lines += ["## Spam (ignored)", ""] + [f"- {e['subject']} (email {e['email_id']})" for e in spam] + [""]
    lines.append("_Drafts are suggestions for you to review. Nothing has been sent._")
    return "\n".join(lines)


def write_summary(analysis: dict, path) -> None:
    path.write_text(build_summary(analysis), encoding="utf-8")