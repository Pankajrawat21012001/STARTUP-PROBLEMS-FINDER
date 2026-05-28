"""
Reddit Problem Discovery Dashboard

Run with: streamlit run dashboard.py
"""

import os
import re
import html as html_lib
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime

# ── Page Config ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Problem Discovery Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Paths ────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PROBLEM_IDS_PATH    = os.path.join(DATA_DIR, "problem_ids.csv")
PROBLEM_EVIDENCE_PATH = os.path.join(DATA_DIR, "problem_evidence.csv")
PROBLEM_SCORES_PATH = os.path.join(DATA_DIR, "problem_scores.csv")
RAW_POSTS_PATH      = os.path.join(DATA_DIR, "raw_posts.csv")

# WTP phrases (kept in sync with step4_wtp_score.py)
WTP_PHRASES = [
    "would pay", "i'd pay", "willing to pay", "worth paying",
    "subscription", "enterprise plan", "our company would", "budget for",
    "paying for", "charge for this", "affordable tool", "worth the money",
    "would buy", "need to purchase",
    "take my money", "shut up and take", "where do i pay",
    "how much does it cost", "is there a paid", "premium version",
    "monthly fee", "annual plan", "per month", "pricing",
    "worth it", "definitely pay", "pay for this",
    "invest in", "spend money on", "need this badly",
    "money well spent", "i wish someone would build",
    "why isn't there a", "why is there no",
    "can't believe there's no", "desperately looking for",
    "tried everything", "no good solution", "nothing works",
    "existing tools are terrible", "current solution is broken",
    "sick of manually", "tired of doing this manually",
    "waste hours", "wastes my time", "time consuming",
    "need a tool", "need software", "need an app",
    "is there an app", "any app for this", "any tool for",
]

URGENCY_PHRASES = [
    "urgent", "critical", "costing us", "losing money", "hours wasted",
    "every day", "daily problem", "manually every", "broken process",
    "nightmare", "so frustrated", "desperately need",
    "massive pain", "huge problem", "real pain point",
    "huge time sink", "takes forever", "kills productivity",
    "inefficient", "waste of time", "painful process",
    "no solution", "workaround", "band-aid solution",
    "fed up", "sick of", "really annoying",
    "tedious", "repetitive task", "manual work",
    "this is ridiculous", "why is this so hard",
]


# ── Helper: Load data ────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_data():
    """Load all CSV files with graceful handling for missing files."""
    dfs = {}
    for name, path in [
        ("problems", PROBLEM_IDS_PATH),
        ("evidence", PROBLEM_EVIDENCE_PATH),
        ("scores",   PROBLEM_SCORES_PATH),
        ("posts",    RAW_POSTS_PATH)
    ]:
        if os.path.exists(path):
            try:
                dfs[name] = pd.read_csv(path, encoding="utf-8")
            except Exception:
                dfs[name] = pd.DataFrame()
        else:
            dfs[name] = pd.DataFrame()
    return dfs


@st.cache_data(ttl=60)
def compute_live_wtp(evidence_df: pd.DataFrame, posts_df: pd.DataFrame) -> pd.DataFrame:
    """
    Re-compute wtp_score per evidence row from raw post text.
    Returns enriched evidence_df with accurate wtp_score & urgency_keywords.
    Called live because step4 is no longer executed in main.py.
    """
    if evidence_df.empty or posts_df.empty:
        return evidence_df

    ev = evidence_df.copy()
    ev["wtp_score"] = 0
    ev["urgency_keywords"] = ""

    post_lookup = posts_df.set_index("post_id") if "post_id" in posts_df.columns else pd.DataFrame()

    for idx, row in ev.iterrows():
        post_id = str(row["post_id"])
        if post_id not in post_lookup.index:
            continue
        post = post_lookup.loc[post_id]
        full_text = " ".join([
            str(post.get("title", "")),
            str(post.get("body", "")),
            str(post.get("top_comments", ""))
        ]).lower()

        wtp_count = sum(1 for p in WTP_PHRASES if p in full_text)
        ev.at[idx, "wtp_score"] = min(wtp_count, 3)
        matched = [p for p in URGENCY_PHRASES if p in full_text]
        ev.at[idx, "urgency_keywords"] = ", ".join(matched)

    return ev


@st.cache_data(ttl=60)
def compute_avg_wtp(problems_df: pd.DataFrame, evidence_df: pd.DataFrame) -> pd.DataFrame:
    """Recalculate avg_wtp_score per problem from live evidence WTP scores."""
    df = problems_df.copy()
    if evidence_df.empty or "wtp_score" not in evidence_df.columns:
        return df
    grouped = (
        evidence_df.groupby("problem_id")["wtp_score"]
        .apply(lambda s: round(pd.to_numeric(s, errors="coerce").fillna(0).mean(), 2))
        .reset_index()
        .rename(columns={"wtp_score": "avg_wtp_score"})
    )
    df = df.drop(columns=["avg_wtp_score"], errors="ignore")
    df = df.merge(grouped, on="problem_id", how="left")
    df["avg_wtp_score"] = df["avg_wtp_score"].fillna(0.0)
    return df


# ── Custom CSS ───────────────────────────────────────────────────
st.markdown("""
<style>
    /* Hide the Deploy toolbar — keep sidebar toggle working */
    [data-testid="stToolbar"]    { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    #MainMenu                    { visibility: hidden; }
    footer                       { visibility: hidden; }

    /* Make the native header invisible but NOT removed — sidebar toggle lives here */
    header[data-testid="stHeader"] {
        background: transparent !important;
        border-bottom: none !important;
        box-shadow: none !important;
        height: 40px !important;
    }

    /* Sidebar expand/collapse control — always visible, themed to match dashboard */
    [data-testid="collapsedControl"] {
        display:       flex        !important;
        visibility:    visible     !important;
        position:      fixed       !important;
        top:           12px        !important;
        left:          12px        !important;
        z-index:       999999      !important;
        background:    rgba(129,140,248,0.18) !important;
        border:        1px solid rgba(129,140,248,0.35) !important;
        border-radius: 8px !important;
        color:         #818cf8     !important;
        padding:       4px         !important;
        cursor:        pointer     !important;
        transition:    background 0.2s, color 0.2s !important;
    }
    [data-testid="collapsedControl"]:hover {
        background: rgba(129,140,248,0.35) !important;
        color:      #c084fc            !important;
    }

    /* Make the sidebar buttons smaller */
    div[data-testid="stSidebar"] button {
        padding: 4px 10px !important;
        font-size: 0.8rem !important;
        min-height: unset !important;
        height: auto !important;
        line-height: 1.4 !important;
        border-radius: 8px !important;
    }

    /* Main background */
    .stApp {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e, #16213e);
        border-right: 1px solid rgba(255,255,255,0.05);
    }

    /* ── Custom top header bar ─────────────────────────── */
    .top-header {
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 14px 24px;
        margin-bottom: 20px;
        background: linear-gradient(90deg,
            rgba(129,140,248,0.12), rgba(192,132,252,0.08), rgba(244,114,182,0.06));
        border-bottom: 1px solid rgba(129,140,248,0.2);
        border-radius: 0 0 16px 16px;
    }
    .top-header h1 {
        font-size: 1.6rem;
        font-weight: 900;
        background: linear-gradient(90deg, #818cf8, #c084fc, #f472b6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
        letter-spacing: -0.3px;
    }
    .top-header .subtitle {
        font-size: 0.8rem;
        color: rgba(255,255,255,0.35);
        margin: 0;
        margin-left: auto;
    }

    /* Metric cards — fixed equal height */
    .metric-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 16px;
        padding: 20px 16px;
        text-align: center;
        height: 110px;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(99, 102, 241, 0.15);
    }
    .metric-value {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #818cf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        line-height: 1.1;
    }
    .metric-sub {
        font-size: 0.72rem;
        color: rgba(248,113,113,0.75);
        font-weight: 500;
        margin: 2px 0;
    }
    .metric-label {
        font-size: 0.75rem;
        color: rgba(255,255,255,0.45);
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 3px;
    }

    /* Problem row */
    .problem-row {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 12px;
        padding: 14px 20px;
        margin-bottom: 8px;
        transition: background 0.2s ease;
    }
    .problem-row:hover { background: rgba(255,255,255,0.06); }

    /* Industry badge */
    .industry-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        background: rgba(99, 102, 241, 0.15);
        color: #818cf8;
        border: 1px solid rgba(99, 102, 241, 0.3);
    }

    /* WTP badge colors */
    .wtp-green { color: #34d399; }
    .wtp-amber { color: #fbbf24; }
    .wtp-red   { color: #f87171; }

    /* Score badge */
    .score-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 0.95rem;
    }
    .score-high { background: rgba(52,211,153,0.15); color:#34d399; border:1px solid rgba(52,211,153,0.3); }
    .score-mid  { background: rgba(251,191,36,0.15);  color:#fbbf24; border:1px solid rgba(251,191,36,0.3); }
    .score-low  { background: rgba(248,113,113,0.15); color:#f87171; border:1px solid rgba(248,113,113,0.3); }

    /* Evidence post card */
    .evidence-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .evidence-body {
        font-size: 0.85rem;
        color: rgba(255,255,255,0.55);
        line-height: 1.5;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }

    /* Subreddit badge */
    .sub-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.7rem;
        background: rgba(244,114,182,0.12);
        color: #f472b6;
        border: 1px solid rgba(244,114,182,0.25);
        margin-right: 6px;
    }

    /* Star styling */
    .wtp-stars { font-size: 1.1rem; }
</style>
""", unsafe_allow_html=True)


# ── Load & enrich data ───────────────────────────────────────────
data = load_data()
problems_df = data["problems"]
evidence_df = data["evidence"]
scores_df   = data["scores"]
posts_df    = data["posts"]

# Re-compute WTP live (step4 is no longer run in the pipeline)
if not evidence_df.empty and not posts_df.empty:
    evidence_df = compute_live_wtp(evidence_df, posts_df)
    problems_df = compute_avg_wtp(problems_df, evidence_df)


# ── Helper functions ─────────────────────────────────────────────
def wtp_color_class(score):
    if score >= 2.0: return "wtp-green"
    if score >= 1.0: return "wtp-amber"
    return "wtp-red"

def score_class(score):
    if score >= 70: return "score-high"
    if score >= 40: return "score-mid"
    return "score-low"

def wtp_stars(score):
    full  = int(score)
    half  = 1 if score - full >= 0.5 else 0
    empty = 3 - full - half
    return "★" * full + "☆" * (half + empty)


# ── Custom top header (replaces Streamlit's Deploy bar) ──────────
st.markdown("""
<div class="top-header">
    <span style="font-size:1.8rem;">🔍</span>
    <h1>Problem Discovery Dashboard</h1>
    <p class="subtitle">Startup problems from Reddit · Scored by AI for market potential</p>
</div>
""", unsafe_allow_html=True)


# ── Top Metric Cards ─────────────────────────────────────────────
total_problems = len(problems_df) if not problems_df.empty else 0
scanned_count  = len(posts_df)   if not posts_df.empty    else 0
noise_count    = 0
if not posts_df.empty and "is_noise" in posts_df.columns:
    noise_count = int(posts_df["is_noise"].astype(str).str.lower().isin(["true","1","1.0"]).sum())

last_run = "Never"
if not posts_df.empty and "scraped_at" in posts_df.columns:
    try:
        last_run = pd.to_datetime(posts_df["scraped_at"]).max().strftime("%Y-%m-%d %H:%M")
    except Exception:
        last_run = "Unknown"

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{total_problems}</div>
        <div class="metric-label">Total Problems Tracked</div>
    </div>""", unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{scanned_count}</div>
        <div class="metric-sub">🗑️ {noise_count} filtered as noise</div>
        <div class="metric-label">Scanned Posts</div>
    </div>""", unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value" style="font-size:1.3rem;">{last_run}</div>
        <div class="metric-label">Last Run Date</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ── Sidebar Filters ───────────────────────────────────────────────
with st.sidebar:
    # Top filters title + small refresh button side by side
    title_col, btn_col = st.columns([3.5, 1])
    with title_col:
        st.markdown("### 🎯 Filters")
    with btn_col:
        st.markdown("<div style='padding-top: 6px;'>", unsafe_allow_html=True)
        if st.button("🔄", help="Refresh data"):
            st.cache_data.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("---")

    # Industry filter
    industries = ["All"]
    if not problems_df.empty and "industry" in problems_df.columns:
        industries += sorted(problems_df["industry"].dropna().unique().tolist())
    selected_industry = st.selectbox("Industry", industries, index=0)

    # Min evidence count
    min_evidence = st.slider("Min Evidence Count", 1, 20, 1)

    # Min WTP score
    min_wtp = st.slider("Min WTP Score", 0.0, 3.0, 0.0, step=0.5)

    # Min LLM score (latest_total_score, max 80)
    min_llm = st.slider("Min LLM Score (/80)", 0, 80, 0, step=5)

    # Min Final Rank score (latest_final_rank_score, max 100)
    min_final = st.slider("Min Final Score (/100)", 0, 100, 0, step=5)

    # Sort by
    sort_options = {
        "Final Rank Score": "latest_final_rank_score",
        "WTP Score":        "avg_wtp_score",
        "Evidence Count":   "evidence_count",
        "Last Seen Date":   "last_seen_date"
    }
    sort_by_label = st.selectbox("Sort By", list(sort_options.keys()))
    sort_by = sort_options[sort_by_label]

    # Top N
    top_n = st.selectbox("Show Top N", [10, 20, 50], index=0)


# ── Apply Filters ────────────────────────────────────────────────
if problems_df.empty:
    st.info(
        "📭 **No data yet.** Run the pipeline first:\n\n"
        "```\npython main.py\n```\n\nThen refresh this page."
    )
    st.stop()

filtered_df = problems_df.copy()

# Convert numeric columns
for col in ["evidence_count", "avg_wtp_score", "latest_total_score", "latest_final_rank_score"]:
    if col in filtered_df.columns:
        filtered_df[col] = pd.to_numeric(filtered_df[col], errors="coerce").fillna(0)

# Apply filters
if selected_industry != "All":
    filtered_df = filtered_df[filtered_df["industry"] == selected_industry]

filtered_df = filtered_df[filtered_df["evidence_count"]           >= min_evidence]
filtered_df = filtered_df[filtered_df["avg_wtp_score"]            >= min_wtp]
filtered_df = filtered_df[filtered_df["latest_total_score"]       >= min_llm]
filtered_df = filtered_df[filtered_df["latest_final_rank_score"]  >= min_final]

# Sort
if sort_by in filtered_df.columns:
    filtered_df = filtered_df.sort_values(sort_by, ascending=False)

# Limit
filtered_df = filtered_df.head(top_n)

if filtered_df.empty:
    st.warning("No problems match the current filters. Try adjusting the sidebar filters.")
    st.stop()


# ── Main Problem List ────────────────────────────────────────────
st.markdown(f"### Showing {len(filtered_df)} problems")

for rank, (idx, problem) in enumerate(filtered_df.iterrows(), 1):
    problem_id    = problem["problem_id"]
    problem_name  = problem.get("problem_name",          "Unknown")
    industry      = problem.get("industry",               "Other")
    evidence_count = int(problem.get("evidence_count",    0))
    avg_wtp        = float(problem.get("avg_wtp_score",   0))
    final_score    = float(problem.get("latest_final_rank_score", 0))
    total_score    = float(problem.get("latest_total_score",      0))
    last_seen      = str(problem.get("last_seen_date",    "N/A"))

    wtp_cls   = wtp_color_class(avg_wtp)
    score_cls = score_class(final_score)

    header_html = f"""
    <div class="problem-row">
        <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center; gap:12px;">
                <span style="font-size:1.3rem; font-weight:800; color:rgba(255,255,255,0.3);">#{rank}</span>
                <span style="font-size:1.05rem; font-weight:600; color:#e2e8f0;">{problem_name}</span>
                <span class="industry-badge">{industry}</span>
            </div>
            <div style="display:flex; align-items:center; gap:16px; flex-wrap:wrap;">
                <span style="font-size:0.85rem; color:rgba(255,255,255,0.5);">📝 {evidence_count}</span>
                <span class="wtp-stars {wtp_cls}">WTP: {avg_wtp:.1f}</span>
                {f'<span style="font-size:0.8rem; font-weight:600; color:#a78bfa; background:rgba(167,139,250,0.12); border:1px solid rgba(167,139,250,0.25); border-radius:6px; padding:2px 8px;">LLM: {total_score:.0f}/80</span>' if total_score > 0 else ''}
                <span class="score-badge {score_cls}">{final_score:.1f}/100</span>
                <span style="font-size:0.8rem; color:rgba(255,255,255,0.35);">{last_seen}</span>
            </div>
        </div>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)

    # Expandable detail
    with st.expander(f"📊 Details — {problem_name}", expanded=(len(filtered_df) == 1)):

        # Load scores for this problem (shared by both columns)
        problem_scores = pd.DataFrame()
        if not scores_df.empty and "problem_id" in scores_df.columns:
            problem_scores = scores_df[scores_df["problem_id"] == problem_id].copy()

        detail_col1, detail_col2 = st.columns([1, 1])

        # ── Score Breakdown ──────────────────────────────────────
        with detail_col1:
            st.markdown("##### 📈 Score Breakdown")

            if not problem_scores.empty:
                latest = problem_scores.sort_values("run_date", ascending=False).iloc[0]

                factor_names = [
                    "Problem Acuteness", "Customer Clarity", "Market Size",
                    "Competition", "Good Ideaspace", "Real Problem",
                    "Tarpit Risk", "Good Proxies"
                ]
                factor_keys = [
                    "problem_acuteness", "customer_clarity", "market_size",
                    "competition", "good_ideaspace", "real_problem",
                    "tarpit_risk", "good_proxies"
                ]

                row1_cols = st.columns(4)
                row2_cols = st.columns(4)
                all_cols  = row1_cols + row2_cols

                for col_widget, name, key in zip(all_cols, factor_names, factor_keys):
                    val = float(latest.get(key, 0))
                    color = "#34d399" if val >= 7 else ("#fbbf24" if val >= 4 else "#f87171")
                    with col_widget:
                        st.markdown(
                            f'<div style="text-align:center; padding:8px 4px; '
                            f'background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); '
                            f'border-radius:8px;">'
                            f'<div style="font-size:0.7rem; color:rgba(255,255,255,0.45); '
                            f'text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px;">{name}</div>'
                            f'<div style="font-size:1.15rem; font-weight:800; color:{color};">{val:.0f}'
                            f'<span style="font-size:0.75rem; color:rgba(255,255,255,0.25);">/10</span></div>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
            else:
                st.info("No scores yet — run step5_groq_score.py to score this problem")

        # ── Score History Chart ──────────────────────────────────
        with detail_col2:
            st.markdown("##### 📉 Score History")

            if not problem_scores.empty:
                problem_scores_sorted = problem_scores.sort_values("run_date")
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=problem_scores_sorted["run_date"],
                    y=problem_scores_sorted["final_rank_score"].astype(float),
                    mode="lines+markers",
                    line=dict(color="#818cf8", width=3),
                    marker=dict(size=8, color="#c084fc"),
                    name="Final Rank Score"
                ))
                fig2.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="white"),
                    height=320,
                    margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(showgrid=False, title="Run Date"),
                    yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)",
                               title="Score /100", range=[0, 100])
                )
                st.plotly_chart(fig2, use_container_width=True,
                                key=f"score_history_{problem_id}")
            else:
                st.info("No score history available yet")

        # ── Evidence Posts ────────────────────────────────────────
        st.markdown("##### 📋 Evidence Posts")

        problem_evidence = pd.DataFrame()
        if not evidence_df.empty and "problem_id" in evidence_df.columns:
            problem_evidence = evidence_df[evidence_df["problem_id"] == problem_id].copy()

        if not problem_evidence.empty and not posts_df.empty:
            merged = problem_evidence.merge(
                posts_df, on="post_id", how="left", suffixes=("_ev", "_post")
            )
            if "upvotes" in merged.columns:
                merged = merged.sort_values("upvotes", ascending=False)

            for _, ev_row in merged.iterrows():
                subreddit  = ev_row.get("subreddit",        "unknown")
                upvotes    = int(ev_row.get("upvotes",      0))
                post_date  = str(ev_row.get("post_created_date", ""))[:10]
                title      = str(ev_row.get("title",        "Untitled"))

                body_raw = str(ev_row.get("body", ""))
                body_raw = body_raw.replace("\n"," ").replace("\r"," ").replace("&#x200B;","").strip()
                body_raw = html_lib.unescape(body_raw)
                body_raw = re.sub(r" +", " ", body_raw)
                body     = body_raw[:400] if len(body_raw) > 400 else body_raw

                top_comments   = str(ev_row.get("top_comments", ""))
                post_url       = ev_row.get("post_url", "")
                wtp_val        = int(ev_row.get("wtp_score", ev_row.get("wtp_score_ev", 0)) or 0)
                urgency        = str(ev_row.get("urgency_keywords", ev_row.get("urgency_keywords_ev", "")) or "")
                similarity_val = float(ev_row.get("similarity_score", 0) or 0)
                stars          = "★" * wtp_val + "☆" * (3 - wtp_val)

                st.markdown(f"""
                <div class="evidence-card">
                    <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">
                        <span class="sub-badge">r/{subreddit}</span>
                        <span style="font-size:0.85rem; font-weight:700; color:#fb923c;
                            background:rgba(251,146,60,0.12); border:1px solid rgba(251,146,60,0.25);
                            border-radius:6px; padding:2px 8px;">⬆ {upvotes:,}</span>
                        <span style="font-size:0.8rem; color:rgba(255,255,255,0.35);">{post_date}</span>
                    </div>
                    <div style="font-weight:600; color:#e2e8f0; margin-bottom:6px;">{title}</div>
                    <div class="evidence-body">{body}</div>
                    <div style="display:flex; gap:12px; align-items:center; margin-top:8px; flex-wrap:wrap;">
                        <span style="font-size:0.75rem; color:rgba(255,255,255,0.4);">
                            🎯 Match: <span style="color:#a78bfa; font-weight:600;">{similarity_val:.0%}</span>
                        </span>
                        <span style="font-size:0.75rem; color:rgba(255,255,255,0.4);">
                            💰 WTP: <span style="color:#fbbf24; font-weight:600;">{wtp_val}/3</span> {stars}
                        </span>
                        {f'<span style="font-size:0.75rem; color:rgba(255,255,255,0.35);">🔑 {urgency}</span>' if urgency else ''}
                    </div>
                    <div style="margin-top:8px;">
                        <a href="{post_url}" target="_blank" style="
                            display:inline-block; margin-top:10px; padding:7px 18px;
                            background:linear-gradient(135deg,rgba(255,69,0,0.18),rgba(255,69,0,0.08));
                            color:#ff6b35; border:1px solid rgba(255,69,0,0.35); border-radius:8px;
                            font-size:0.82rem; font-weight:600; text-decoration:none;
                            letter-spacing:0.3px; transition:background 0.2s;">
                            🔗 View on Reddit ↗
                        </a>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                if top_comments and top_comments != "nan":
                    comments_list = top_comments.split(" || ")
                    with st.expander("💬 Top comments", expanded=False):
                        for ci, comment in enumerate(comments_list):
                            st.markdown(f"**Comment {ci+1}:** {comment}")
        else:
            st.info("No evidence posts linked to this problem")

        # ── Score History Table ───────────────────────────────────
        if not problem_scores.empty:
            st.markdown("##### 📊 Score History Table")
            display_cols = [
                "run_date", "problem_acuteness", "customer_clarity", "market_size",
                "competition", "good_ideaspace", "real_problem", "tarpit_risk",
                "good_proxies", "total_score", "freshness_weight", "final_rank_score"
            ]
            available_cols = [c for c in display_cols if c in problem_scores.columns]
            st.dataframe(
                problem_scores[available_cols].sort_values("run_date", ascending=False),
                use_container_width=True,
                hide_index=True
            )

    st.markdown("")  # spacer between problems
