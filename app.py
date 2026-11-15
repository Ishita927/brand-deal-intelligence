"""Streamlit UI.  Run:  streamlit run app.py"""
import hmac
import json
import os
import re
from datetime import date
from pathlib import Path

import streamlit as st

from brand_deals.config import GEMINI_MODEL
from brand_deals.llm import GeminiClient
from brand_deals.loader import parse_emails, parse_profile
from brand_deals.pipeline import run_pipeline
from brand_deals.reporting import build_summary
from brand_deals.utils import parse_date
from evaluate import evaluate

st.set_page_config(page_title="Brand Deal Inbox", page_icon="📬", layout="wide")


def secret(name):
    """Server-side secret (Streamlit Cloud Secrets or .streamlit/secrets.toml). Never sent to the browser."""
    try:
        return str(st.secrets[name])
    except Exception:
        return ""


def password_ok():
    """If APP_PASSWORD is set in the secrets, ask for it before showing anything. No secret = no gate (local use)."""
    expected = secret("APP_PASSWORD")
    if not expected or st.session_state.get("authed"):
        return True
    st.title("Brand Deal Inbox")
    typed = st.text_input("Password", type="password", key="pw")
    if typed and hmac.compare_digest(typed.encode(), expected.encode()):
        st.session_state.authed = True
        st.rerun()
    elif typed:
        st.error("Wrong password.")
    return False


if not password_ok():
    st.stop()

ACTION_LABEL = {"accept": "Accept", "negotiate": "Negotiate", "ask_for_details": "Ask for details",
                "decline": "Decline", "ignore_or_report": "Ignore / report"}
CATEGORY_LABEL = {"deal_offer": "Deal offer", "needs_more_info": "Needs more info", "not_a_fit": "Not a fit",
                  "scam_or_phishing": "Scam or phishing", "spam": "Spam"}
SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}
STATUSES = ["New", "Replied", "Done"]


# ---------------------------------------------------------------- helpers
def read_json(upload, default_path):
    """Uploaded file first, else the file on disk, else None.
    Raises ValueError with a readable message if the file is empty or not valid JSON."""
    if upload is not None:
        name, text = upload.name, upload.getvalue().decode("utf-8-sig")
    else:
        path = Path(default_path)
        if not path.exists():
            return None
        name, text = str(path), path.read_text(encoding="utf-8-sig")   # utf-8-sig also handles Notepad's BOM
    if not text.strip():
        raise ValueError(f"{name} is empty.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{name} is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}.") from e


def run_analysis(inbox_up, profile_up, api_key, model, today_text, ai_drafts):
    try:
        raw_inbox = read_json(inbox_up, "data/inbox.json")
        raw_profile = read_json(profile_up, "data/creator_profile.json")
    except ValueError as e:
        st.error(str(e))
        return
    if raw_inbox is None or raw_profile is None:
        st.error("Upload an inbox file and a creator profile, or put them in the data/ folder.")
        return
    emails, profile = parse_emails(raw_inbox), parse_profile(raw_profile)
    dates = [d for d in (parse_date(e.date) for e in emails) if d]
    today = parse_date(today_text) or (max(dates) if dates else date.today())

    bar = st.progress(0.0, text="Starting")

    def progress(msg):                                  # pipeline sends "[8/15] analysed 8 of 15 emails"
        m = re.match(r"\[(\d+)/(\d+)\]", msg)
        if m:
            bar.progress(int(m[1]) / int(m[2]), text=msg)

    try:
        analysis = run_pipeline(emails, profile, today, GeminiClient(api_key=api_key, model=model),
                                progress=progress, ai_drafts=ai_drafts)
    except Exception as e:
        bar.empty()
        st.error(f"Could not run the analysis: {e}")
        return
    bar.empty()

    out = Path("outputs")                               # same files the command line version writes
    out.mkdir(exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.md").write_text(build_summary(analysis), encoding="utf-8")

    st.session_state.analysis = analysis
    st.session_state.emails = {e.id: e.model_dump() for e in emails}
    for key in [k for k in st.session_state if k.startswith(("status_", "subj_", "body_"))]:
        del st.session_state[key]                       # forget edits from the previous run


def money(amount, currency):
    return f"{currency or ''} {amount:,.0f}".strip() if amount is not None else "Not stated"


# ---------------------------------------------------------------- sidebar (inputs)
with st.sidebar:
    st.header("Inputs")
    inbox_up = st.file_uploader("Inbox (JSON)", type="json", key="inbox_up")
    profile_up = st.file_uploader("Creator profile (JSON)", type="json", key="profile_up")
    st.caption("Leave empty to use data/inbox.json and data/creator_profile.json.")
    api_key_input = st.text_input("Gemini API key", type="password", key="api_key",
                                  help="Optional if the server already has a key. Your key is only used for your own runs.")
    api_key = api_key_input or secret("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY", "")   # server key stays server-side
    model = st.text_input("Model", value=GEMINI_MODEL, key="model")
    today_text = st.text_input("Today's date (optional, YYYY-MM-DD)", key="today_text",
                               help="Default: the date of the newest email.")
    ai_drafts = st.checkbox("Polish reply drafts with AI (slower)", value=False, key="ai_drafts",
                            help="Drafts are written instantly from templates. Tick this for one extra model call that rewrites them.")
    if st.button("Analyze inbox", type="primary", key="run"):
        run_analysis(inbox_up, profile_up, api_key, model, today_text, ai_drafts)
    if st.button("Check Gemini connection", key="check"):
        try:
            ok, message = GeminiClient(api_key=api_key, model=model).check()
        except Exception as e:
            ok, message = False, str(e)
        (st.success if ok else st.error)(message)

# ---------------------------------------------------------------- main page
st.title("Brand Deal Inbox")
analysis = st.session_state.get("analysis")
if not analysis:
    st.info("Choose your files in the sidebar and press **Analyze inbox**.")
    st.stop()

stats, deals, emails = analysis["stats"], analysis["deals"], st.session_state.emails
suspicious = sum(d["category"] == "scam_or_phishing" for d in deals)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Emails", stats["emails"])
c2.metric("Unique deals", stats["deals"])
c3.metric("Need your reply", stats["needs_attention"])
c4.metric("Suspicious", suspicious)
if stats["analysis_errors"]:
    st.error(f"{stats['analysis_errors']} of {stats['emails']} emails could not be analysed. First error: {stats['first_error']}")
for w in analysis.get("warnings", []):
    st.warning(w)

tab_deals, tab_emails, tab_summary, tab_eval, tab_raw = st.tabs(
    ["Deals", "Emails", "Daily summary", "Evaluation", "Raw data"])

# ---- Deals
with tab_deals:
    shown = st.multiselect("Show", list(ACTION_LABEL), default=["accept", "negotiate", "ask_for_details"],
                           format_func=ACTION_LABEL.get, key="filter_actions")
    visible = [d for d in deals if d["recommended_action"] in shown]
    if not visible:
        st.write("No deals match this filter.")
    for d in visible:
        did = d["deal_id"]
        with st.container(border=True):
            left, right = st.columns([4, 1])
            left.subheader(d["headline"])
            who = " ".join(x for x in [d["contact_name"], d["contact_email"]] if x) or "unknown contact"
            left.caption(f"{did}. Emails {', '.join(d['email_ids'])}. Contact: {who}")
            right.markdown(f"**{ACTION_LABEL[d['recommended_action']]}**")
            right.selectbox("Status", STATUSES, key=f"status_{did}")

            a, b, c, e = st.columns(4)
            a.metric("Offer", money(d["fee"], d["currency"]))
            b.metric("Payment", d["payment_type"])
            c.metric("Deadline", d["deadline"] or "Not stated")
            e.metric("Type", CATEGORY_LABEL[d["category"]])
            if d["usage_rights"]:
                st.write(f"**Usage rights:** {d['usage_rights']}")

            for f in d["risk_flags"]:
                st.markdown(f"{SEVERITY_ICON[f['severity']]} {f['reason']}")
            if d["recommended_action"] == "ask_for_details" and d["missing_info"]:
                st.write("**Still missing:** " + ", ".join(d["missing_info"]))

            if d["reply_draft"]:
                with st.expander("Reply draft (edit it, nothing is sent)"):
                    subject = st.text_input("Subject", value=d["reply_draft"]["subject"], key=f"subj_{did}")
                    body = st.text_area("Body", value=d["reply_draft"]["body"], height=220, key=f"body_{did}")
                    st.download_button("Download draft", f"Subject: {subject}\n\n{body}",
                                       file_name=f"{did}_reply.txt", key=f"dl_{did}")
            with st.expander("Original emails"):
                for eid in d["email_ids"]:
                    em = emails[eid]
                    st.markdown(f"**{em['subject']}**  \nFrom {em['sender']} on {em['date']}")
                    st.text(em["body"])

# ---- Emails
with tab_emails:
    st.dataframe([{"id": r["email_id"], "from": r["sender"], "subject": r["subject"],
                   "category": CATEGORY_LABEL[r["category"]], "deal": r["deal_id"] or "-",
                   "reason": r["category_reason"], "error": r["error"] or ""} for r in analysis["emails"]],
                 width="stretch", hide_index=True)

# ---- Summary
with tab_summary:
    summary = build_summary(analysis)
    st.markdown(summary)
    st.download_button("Download summary.md", summary, file_name="summary.md", key="dl_summary")

# ---- Evaluation
with tab_eval:
    st.write("Compare the results with your hand-written expected answers.")
    exp_up = st.file_uploader("expected.json", type="json", key="exp_up")
    expected, problem = None, None
    try:
        expected = read_json(exp_up, "data/expected.json")
    except ValueError as e:
        problem = str(e)

    if problem:
        st.error(problem + " Run `python evaluate.py --init` for a template, fill it in, and save it as data/expected.json.")
    elif expected is None:
        st.info("No expected.json yet. Run `python evaluate.py --init`, fill the template in by reading the emails, then save it as data/expected.json or upload it here.")
    elif not isinstance(expected, dict) or not isinstance(expected.get("emails"), dict):
        st.error('expected.json must have an "emails" section. Use the template from `python evaluate.py --init`.')
    elif all(isinstance(v, dict) and v.get("category") is None for v in expected["emails"].values()):
        st.warning("expected.json is still the empty template. Fill in a category for each email first.")
    elif st.button("Run evaluation", key="run_eval"):
        report = evaluate(analysis, expected)
        m1, m2, m3 = st.columns(3)
        m1.metric("Category accuracy", report["category_accuracy"])
        m2.metric("Grouping precision", report["grouping"]["pair_precision"])
        m3.metric("Grouping recall", report["grouping"]["pair_recall"])
        st.write("**Deal fields:**", report["deal_fields"])
        if report["category_mismatches"]:
            st.write("**Wrong categories**")
            st.dataframe(report["category_mismatches"], width="stretch", hide_index=True)
        if report["deal_problems"]:
            st.write("**Wrong deal fields**")
            st.dataframe(report["deal_problems"], width="stretch", hide_index=True)
        st.download_button("Download evaluation_report.json", json.dumps(report, indent=2, ensure_ascii=False),
                           file_name="evaluation_report.json", key="dl_eval")

# # ---- Raw
# with tab_raw:
#     st.download_button("Download analysis.json", json.dumps(analysis, indent=2, ensure_ascii=False),
#                        file_name="analysis.json", key="dl_analysis")
#     st.json(analysis, expanded=False)