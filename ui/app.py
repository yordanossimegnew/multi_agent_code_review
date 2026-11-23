"""Streamlit front end for the Multi-Agent Code Review panel.

    uvicorn main:app            # terminal 1
    streamlit run ui/app.py     # terminal 2
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

import requests
import streamlit as st

API_URL = os.getenv("AGENT_API_URL", "http://localhost:8000")
EXAMPLE_DIFF = (Path(__file__).resolve().parents[1] / "data" / "examples" / "user_service.diff").read_text()

SEV = {"critical": ("#7f1d1d", "#fee2e2", "🔴"), "high": ("#b91c1c", "#fee2e2", "🟠"),
       "medium": ("#a16207", "#fef9c3", "🟡"), "low": ("#475569", "#f1f5f9", "⚪")}
VERDICT = {"approve": ("✅ Approve", "#166534", "#dcfce7"), "comment": ("💬 Comment", "#854d0e", "#fef9c3"),
           "request_changes": ("⛔ Request changes", "#991b1b", "#fee2e2")}

st.set_page_config(page_title="Code Review Panel", page_icon="🧑‍⚖️", layout="wide")
st.markdown("""<style>
.card {border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;height:118px;background:#fff}
.card h4 {margin:0 0 6px 0;font-size:0.95rem}
.card .st {font-size:0.85rem;color:#475569}
.card.done {border-color:#86efac;background:#f0fdf4} .card.run {border-color:#93c5fd;background:#eff6ff}
.card.fail {border-color:#fca5a5;background:#fef2f2}
.verdict {padding:14px 18px;border-radius:10px;font-size:1.25rem;font-weight:700;margin:8px 0}
.sev {display:inline-block;padding:1px 8px;border-radius:9px;font-size:0.75rem;font-weight:700;margin-right:6px}
.chip {display:inline-block;padding:0 7px;border-radius:9px;background:#eef2ff;color:#3730a3;font-size:0.75rem;margin-right:4px}
.code {font:12.5px/1.55 Consolas,'JetBrains Mono',monospace;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;margin:6px 0}
.code div {white-space:pre;padding:0 10px} .code .n {display:inline-block;width:38px;color:#94a3b8;user-select:none}
.code .add {background:#ecfdf5} .code .del {background:#fef2f2;color:#991b1b} .code .hit {background:#fde68a !important;font-weight:600}
.code .note {margin:2px 0 6px 48px;padding:6px 10px;border-left:3px solid #f59e0b;background:#fffbeb;font:13px sans-serif;white-space:normal}
</style>""", unsafe_allow_html=True)


# ----------------------------------------------------------------------------- API
def api(method, path, **kw):
    try:
        r = requests.request(method, f"{API_URL}{path}", timeout=15, **kw)
        return r.json() if r.ok else {"_error": r.json().get("detail", r.text)}
    except requests.RequestException as exc:
        return {"_error": str(exc)}


def stream(url):
    with requests.get(f"{API_URL}{url}", stream=True, timeout=(5, 600)) as r:
        for line in r.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                yield json.loads(line[6:])


# ----------------------------------------------------------------------------- rendering helpers
def card(slot, icon, name, status, css=""):
    slot.markdown(f'<div class="card {css}"><h4>{icon} {name}</h4><div class="st">{status}</div></div>',
                  unsafe_allow_html=True)


def sev_badge(severity):
    fg, bg, _ = SEV[severity]
    return f'<span class="sev" style="color:{fg};background:{bg}">{severity.upper()}</span>'


def code_context(files, path, line, radius=3):
    f = next((f for f in files if f["path"] == path), None)
    if not f or not line:
        return ""
    for h in f["hunks"]:
        lines = h["lines"]
        idx = next((i for i, l in enumerate(lines) if l["new_no"] == line), None)
        if idx is None:
            continue
        rows = []
        for l in lines[max(0, idx - radius): idx + radius + 1]:
            css = {"+": "add", "-": "del", " ": ""}[l["kind"]] + (" hit" if l["new_no"] == line else "")
            num = l["new_no"] if l["new_no"] is not None else ""
            rows.append(f'<div class="{css}"><span class="n">{num}</span>{l["kind"]} {html.escape(l["text"])}</div>')
        return f'<div class="code">{"".join(rows)}</div>'
    return ""


def render_report(detail, files, reviewers):
    report = detail["report"]
    label, fg, bg = VERDICT[report["verdict"]]
    st.markdown(f'<div class="verdict" style="color:{fg};background:{bg}">{label}</div>', unsafe_allow_html=True)
    st.markdown(report["summary"])
    counts = {s: sum(f["severity"] == s for f in report["findings"]) for s in SEV}
    cols = st.columns(6)
    for col, (s, n) in zip(cols, counts.items()):
        col.metric(f"{SEV[s][2]} {s.title()}", n)
    usage = detail.get("usage") or {}
    cols[4].metric("Dismissed", len(report["dismissed"]))
    cols[5].metric("Tokens", f"{usage.get('input_tokens', 0) + usage.get('output_tokens', 0):,}")

    t1, t2, t3 = st.tabs(["🔎 Findings", "📄 Files changed", "🧑‍🤝‍🧑 Panel"])
    with t1:
        if not report["findings"]:
            st.success("No problems found.")
        for f in report["findings"]:
            where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
            icon = SEV[f["severity"]][2]
            with st.expander(f"{icon} {f['id']} · {where} · {f['title']}", expanded=f["severity"] in ("critical", "high")):
                chips = "".join(f'<span class="chip">{reviewers.get(r, {}).get("icon", "")} {r}</span>' for r in f["raised_by"])
                loc = "" if f["location"] in ("exact", "file") else f' · location <b>{f["location"]}</b>'
                st.markdown(f'{sev_badge(f["severity"])} <b>{f["category"]}</b> · confidence {f["confidence"]}{loc} · raised by {chips}',
                            unsafe_allow_html=True)
                st.markdown(code_context(files, f["file"], f["line"]), unsafe_allow_html=True)
                st.markdown(f["explanation"])
                st.markdown(f"**Suggested fix:** {f['suggestion']}")
    with t2:
        notes = {}
        for f in report["findings"]:
            notes.setdefault((f["file"], f["line"]), []).append(f)
        for f in files:
            st.markdown(f"**{f['path']}** · {f['status']} · :green[+{f['additions']}] :red[-{f['deletions']}]")
            rows = []
            for h in f["hunks"]:
                rows.append(f'<div style="color:#6366f1;background:#eef2ff">{html.escape(h["header"])}</div>')
                for l in h["lines"]:
                    css = {"+": "add", "-": "del", " ": ""}[l["kind"]]
                    num = l["new_no"] if l["new_no"] is not None else ""
                    rows.append(f'<div class="{css}"><span class="n">{num}</span>{l["kind"]} {html.escape(l["text"])}</div>')
                    for n in notes.get((f["path"], l["new_no"]), []) if l["new_no"] else []:
                        rows.append(f'<div class="note">{sev_badge(n["severity"])}<b>{html.escape(n["title"])}</b>: '
                                    f'{html.escape(n["explanation"])}</div>')
            st.markdown(f'<div class="code">{"".join(rows)}</div>', unsafe_allow_html=True)
    with t3:
        for r in detail["reviews"]:
            info = reviewers.get(r["reviewer"], {})
            st.markdown(f"#### {info.get('icon', '')} {info.get('name', r['reviewer'])}")
            if r.get("error"):
                st.error(r["error"])
                continue
            st.caption(r["summary"])
            for f in r["findings"]:
                st.markdown(f'- {sev_badge(f["severity"])} `{f["file"]}:{f["line"]}` {html.escape(f["title"])}',
                            unsafe_allow_html=True)
        if report["dismissed"]:
            st.markdown("#### 🗑️ Dismissed by the lead reviewer")
            for d in report["dismissed"]:
                st.markdown(f"- **{d['title']}** ({', '.join(d['raised_by'])}): {d['reason']}")


# ----------------------------------------------------------------------------- page
health = api("GET", "/health")
ok = health and "_error" not in health
reviewers = {r["key"]: r for r in (api("GET", "/reviewers") or [])} if ok else {}

with st.sidebar:
    st.title("🧑‍⚖️ Code Review Panel")
    st.caption("Four LangGraph specialists in parallel + a lead reviewer")
    if ok:
        st.success("API connected", icon="✅")
        st.markdown(f"**Model:** `{health['model']}`")
    else:
        st.error(f"API not reachable at {API_URL}. Start it with `uvicorn main:app`.", icon="🚫")
    st.markdown("**Reviewers**")
    chosen = [k for k, r in reviewers.items() if st.checkbox(f"{r['icon']} {r['name']}", value=True, key=f"rv-{k}")]
    past = api("GET", "/reviews") if ok else []
    if isinstance(past, list) and past:
        st.divider()
        labels = {f"{p['title'][:40] or 'review'} · {p['verdict'] or p['status']}": p["review_id"] for p in past}
        pick = st.selectbox("Past reviews", ["—", *labels])
        if pick != "—":
            st.session_state.review_id = labels[pick]

tab_pr, tab_diff = st.tabs(["🔗 GitHub pull request", "📋 Paste a diff"])
with tab_pr:
    pr_url = st.text_input("Public PR URL", placeholder="https://github.com/owner/repo/pull/123")
    run_pr = st.button("Review pull request", type="primary", disabled=not (ok and pr_url and chosen))
with tab_diff:
    if st.button("Load example diff (user service with planted bugs)"):
        st.session_state.diff_text = EXAMPLE_DIFF
        st.session_state.diff_title = "Add user search, pagination and password hashing"
    title = st.text_input("Title", key="diff_title")
    diff_text = st.text_area("Unified diff", key="diff_text", height=220, placeholder="Paste `git diff` output…")
    run_diff = st.button("Review diff", type="primary", disabled=not (ok and diff_text.strip() and chosen))

payload = None
if run_pr:
    payload = {"pr_url": pr_url, "reviewers": chosen}
elif run_diff:
    payload = {"diff": diff_text, "title": title, "reviewers": chosen}

if payload:
    created = api("POST", "/reviews", json=payload)
    if "_error" in created:
        st.error(created["_error"])
    else:
        st.session_state.review_id = created["review_id"]
        st.markdown("### Review panel")
        slots = {k: col.empty() for k, col in zip([*chosen, "lead"], st.columns(len(chosen) + 1))}
        for k in chosen:
            card(slots[k], reviewers[k]["icon"], reviewers[k]["name"].replace(" reviewer", ""), "⏳ waiting")
        card(slots["lead"], "🧑‍⚖️", "Lead reviewer", "⏳ waits for the panel")
        status = st.empty()
        for ev in stream(created["events_url"]):
            kind = ev["type"]
            if kind == "fetching":
                status.info(f"Fetching {ev['url']} …")
            elif kind == "prepared":
                n = sum(f["additions"] + f["deletions"] for f in ev["files"])
                status.info(f"Reviewing {len(ev['files'])} file(s), {n} changed lines…")
            elif kind in ("specialist_started", "specialist_done", "specialist_failed"):
                r = reviewers[ev["reviewer"]]
                text, css = {"specialist_started": ("🔍 reviewing…", "run"),
                             "specialist_done": (f"✅ {ev.get('count', 0)} finding(s)", "done"),
                             "specialist_failed": ("❌ failed", "fail")}[kind]
                card(slots[ev["reviewer"]], r["icon"], r["name"].replace(" reviewer", ""), text, css)
            elif kind == "lead_started":
                card(slots["lead"], "🧑‍⚖️", "Lead reviewer", "🔍 verifying & ranking…", "run")
            elif kind == "lead_done":
                card(slots["lead"], "🧑‍⚖️", "Lead reviewer", f"✅ {ev['count']} verified finding(s)", "done")
            elif kind == "error":
                status.error(ev["message"])
            elif kind == "done":
                status.empty()

review_id = st.session_state.get("review_id")
if review_id:
    detail = api("GET", f"/reviews/{review_id}")
    if detail and detail.get("report"):
        diff = api("GET", f"/reviews/{review_id}/diff")
        st.divider()
        st.markdown(f"## {detail['title'] or 'Review'}")
        render_report(detail, diff.get("files", []), reviewers)
    elif detail and detail.get("error") and not payload:
        st.error(detail["error"])
