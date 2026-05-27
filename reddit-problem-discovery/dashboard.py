"""
Reddit Problem Discovery Dashboard

Run with: streamlit run dashboard.py
"""

import os
import pandas as pd
import streamlit as st
import plotly.express as px
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
PROBLEM_IDS_PATH = os.path.join(DATA_DIR, "problem_ids.csv")
PROBLEM_EVIDENCE_PATH = os.path.join(DATA_DIR, "problem_evidence.csv")
PROBLEM_SCORES_PATH = os.path.join(DATA_DIR, "problem_scores.csv")
RAW_POSTS_PATH = os.path.join(DATA_DIR, "raw_posts.csv")


# ── Helper: Load data ───────────────────────────────────────────
@st.cache_data(ttl=60)
def load_data():
    """Load all CSV files with graceful handling for missing files."""
    dfs = {}
    for name, path in [
        ("problems", PROBLEM_IDS_PATH),
        ("evidence", PROBLEM_EVIDENCE_PATH),
        ("scores", PROBLEM_SCORES_PATH),
        ("posts", RAW_POSTS_PATH)
    ]:
        if os.path.exists(path):
            try:
                dfs[name] = pd.read_csv(path, encoding="utf-8")
            except Exception:
                dfs[name] = pd.DataFrame()
        else:
            dfs[name] = pd.DataFrame()
    return dfs


# ── Custom CSS ───────────────────────────────────────────────────
st.markdown("""
<style>
    /* Main background */
    .stApp {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e, #16213e);
        border-right: 1px solid rgba(255,255,255,0.05);
    }

    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 16px;
        padding: 24px;
        text-align: center;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(99, 102, 241, 0.15);
    }
    .metric-value {
        font-size: 2.4rem;
        font-weight: 700;
        background: linear-gradient(90deg, #818cf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 4px;
    }
    .metric-label {
        font-size: 0.85rem;
        color: rgba(255,255,255,0.5);
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    /* Problem row */
    .problem-row {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 8px;
        transition: background 0.2s ease;
    }
    .problem-row:hover {
        background: rgba(255,255,255,0.06);
    }

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
    .wtp-red { color: #f87171; }

    /* Score badge */
    .score-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 0.95rem;
    }
    .score-high {
        background: rgba(52, 211, 153, 0.15);
        color: #34d399;
        border: 1px solid rgba(52, 211, 153, 0.3);
    }
    .score-mid {
        background: rgba(251, 191, 36, 0.15);
        color: #fbbf24;
        border: 1px solid rgba(251, 191, 36, 0.3);
    }
    .score-low {
        background: rgba(248, 113, 113, 0.15);
        color: #f87171;
        border: 1px solid rgba(248, 113, 113, 0.3);
    }

    /* Evidence post card */
    .evidence-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
    }

    /* Title styling */
    .dashboard-title {
        font-size: 2rem;
        font-weight: 800;
        background: linear-gradient(90deg, #818cf8, #c084fc, #f472b6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 8px;
    }

    /* Subreddit badge */
    .sub-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.7rem;
        background: rgba(244, 114, 182, 0.12);
        color: #f472b6;
        border: 1px solid rgba(244, 114, 182, 0.25);
        margin-right: 6px;
    }

    /* Hide default streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Star styling */
    .wtp-stars { font-size: 1.1rem; }
</style>
""", unsafe_allow_html=True)


# ── Load Data ────────────────────────────────────────────────────
data = load_data()
problems_df = data["problems"]
evidence_df = data["evidence"]
scores_df = data["scores"]
posts_df = data["posts"]


# ── Helper functions ─────────────────────────────────────────────
def wtp_color_class(score):
    """Return CSS class based on WTP score."""
    if score >= 2.0:
        return "wtp-green"
    elif score >= 1.0:
        return "wtp-amber"
    return "wtp-red"


def score_class(score):
    """Return CSS class based on final rank score."""
    if score >= 70:
        return "score-high"
    elif score >= 40:
        return "score-mid"
    return "score-low"


def wtp_stars(score):
    """Convert WTP score to star display."""
    full = int(score)
    half = 1 if score - full >= 0.5 else 0
    empty = 3 - full - half
    return "★" * full + "☆" * (half + empty)


# ── Title ────────────────────────────────────────────────────────
st.markdown('<p class="dashboard-title">🔍 Problem Discovery Dashboard</p>', unsafe_allow_html=True)

# ── Top Metric Cards ────────────────────────────────────────────
col1, col2, col3 = st.columns(3)

total_problems = len(problems_df) if not problems_df.empty else 0
total_evidence = len(evidence_df) if not evidence_df.empty else 0
last_run = "Never"
if not posts_df.empty and "scraped_at" in posts_df.columns:
    try:
        last_run = pd.to_datetime(posts_df["scraped_at"]).max().strftime("%Y-%m-%d %H:%M")
    except Exception:
        last_run = "Unknown"

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{total_problems}</div>
        <div class="metric-label">Total Problems Tracked</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{total_evidence}</div>
        <div class="metric-label">Total Evidence Posts</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value" style="font-size: 1.6rem;">{last_run}</div>
        <div class="metric-label">Last Run Date</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ── Sidebar Filters ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🎯 Filters")
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

    # Sort by
    sort_options = {
        "Final Rank Score": "latest_final_rank_score",
        "WTP Score": "avg_wtp_score",
        "Evidence Count": "evidence_count",
        "Last Seen Date": "last_seen_date"
    }
    sort_by_label = st.selectbox("Sort By", list(sort_options.keys()))
    sort_by = sort_options[sort_by_label]

    # Top N
    top_n = st.selectbox("Show Top N", [10, 20, 50], index=0)

    st.markdown("---")
    st.markdown("### 📊 About")
    st.markdown(
        "This dashboard displays startup problems discovered from Reddit, "
        "scored by AI for market potential."
    )
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()


# ── Apply Filters ────────────────────────────────────────────────
if problems_df.empty:
    st.info(
        "📭 **No data yet.** Run the pipeline first:\n\n"
        "```\npython main.py\n```\n\n"
        "Then refresh this page."
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

filtered_df = filtered_df[filtered_df["evidence_count"] >= min_evidence]
filtered_df = filtered_df[filtered_df["avg_wtp_score"] >= min_wtp]

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
    problem_id = problem["problem_id"]
    problem_name = problem.get("problem_name", "Unknown")
    industry = problem.get("industry", "Other")
    evidence_count = int(problem.get("evidence_count", 0))
    avg_wtp = float(problem.get("avg_wtp_score", 0))
    final_score = float(problem.get("latest_final_rank_score", 0))
    last_seen = str(problem.get("last_seen_date", "N/A"))

    wtp_cls = wtp_color_class(avg_wtp)
    score_cls = score_class(final_score)

    # Problem header row
    header_html = f"""
    <div class="problem-row">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="font-size: 1.3rem; font-weight: 800; color: rgba(255,255,255,0.3);">#{rank}</span>
                <span style="font-size: 1.05rem; font-weight: 600; color: #e2e8f0;">{problem_name}</span>
                <span class="industry-badge">{industry}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 16px;">
                <span style="font-size: 0.85rem; color: rgba(255,255,255,0.5);">📝 {evidence_count}</span>
                <span class="wtp-stars {wtp_cls}">WTP: {avg_wtp:.1f}</span>
                <span class="score-badge {score_cls}">{final_score:.1f}/100</span>
                <span style="font-size: 0.8rem; color: rgba(255,255,255,0.35);">{last_seen}</span>
            </div>
        </div>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)

    # Expandable detail
    with st.expander(f"📊 Details — {problem_name}", expanded=False):

        detail_col1, detail_col2 = st.columns([1, 1])

        # ── Section 1: Score Breakdown ───────────────────────────
        with detail_col1:
            st.markdown("##### 📈 Score Breakdown")

            # Get latest scores for this problem
            problem_scores = pd.DataFrame()
            if not scores_df.empty and "problem_id" in scores_df.columns:
                problem_scores = scores_df[scores_df["problem_id"] == problem_id].copy()

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
                factor_values = [
                    float(latest.get(k, 0)) for k in factor_keys
                ]

                fig = go.Figure(go.Bar(
                    x=factor_values,
                    y=factor_names,
                    orientation="h",
                    marker=dict(
                        color=factor_values,
                        colorscale=[[0, "#f87171"], [0.5, "#fbbf24"], [1, "#34d399"]],
                        cmin=1, cmax=10
                    ),
                    text=[f"{v:.0f}/10" for v in factor_values],
                    textposition="outside",
                    textfont=dict(color="white", size=12)
                ))
                fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="white"),
                    height=320,
                    margin=dict(l=10, r=40, t=10, b=10),
                    xaxis=dict(range=[0, 11], showgrid=False),
                    yaxis=dict(showgrid=False)
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No scores yet — problem needs ≥3 evidence posts and WTP ≥1.0")

        # ── Score History Chart ──────────────────────────────────
        with detail_col2:
            st.markdown("##### 📉 Score History")

            if not problem_scores.empty and len(problem_scores) > 0:
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
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("No score history available yet")

        # ── Section 2: Evidence Posts ────────────────────────────
        st.markdown("##### 📋 Evidence Posts")

        problem_evidence = pd.DataFrame()
        if not evidence_df.empty and "problem_id" in evidence_df.columns:
            problem_evidence = evidence_df[evidence_df["problem_id"] == problem_id].copy()

        if not problem_evidence.empty and not posts_df.empty:
            # Merge evidence with raw posts
            merged = problem_evidence.merge(
                posts_df,
                on="post_id",
                how="left",
                suffixes=("_ev", "_post")
            )

            # Sort by upvotes desc
            if "upvotes" in merged.columns:
                merged = merged.sort_values("upvotes", ascending=False)

            for _, ev_row in merged.iterrows():
                subreddit = ev_row.get("subreddit", "unknown")
                upvotes = int(ev_row.get("upvotes", 0))
                post_date = str(ev_row.get("post_created_date", ""))[:10]
                title = str(ev_row.get("title", "Untitled"))
                body = str(ev_row.get("body", ""))
                if len(body) > 300:
                    body = body[:300] + "..."
                top_comments = str(ev_row.get("top_comments", ""))
                post_url = ev_row.get("post_url", "")
                wtp_val = int(ev_row.get("wtp_score", ev_row.get("wtp_score_ev", 0)) or 0)
                urgency = str(ev_row.get("urgency_keywords", ev_row.get("urgency_keywords_ev", "")) or "")

                stars = "★" * wtp_val + "☆" * (3 - wtp_val)

                st.markdown(f"""
                <div class="evidence-card">
                    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
                        <span class="sub-badge">r/{subreddit}</span>
                        <span style="font-size: 0.8rem; color: rgba(255,255,255,0.4);">⬆ {upvotes}</span>
                        <span style="font-size: 0.8rem; color: rgba(255,255,255,0.35);">{post_date}</span>
                        <span class="wtp-stars" style="margin-left: auto;">{stars}</span>
                    </div>
                    <div style="font-weight: 600; color: #e2e8f0; margin-bottom: 6px;">{title}</div>
                    <div style="font-size: 0.85rem; color: rgba(255,255,255,0.55); line-height: 1.5;">{body}</div>
                    {"<div style='font-size: 0.75rem; color: rgba(255,255,255,0.3); margin-top: 4px;'>🔑 " + urgency + "</div>" if urgency else ""}
                    <div style="margin-top: 8px;">
                        <a href="{post_url}" target="_blank" style="color: #818cf8; font-size: 0.85rem; text-decoration: none;">View on Reddit →</a>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Collapsed comments
                if top_comments and top_comments != "nan":
                    comments_list = top_comments.split(" || ")
                    with st.expander("💬 Top comments", expanded=False):
                        for ci, comment in enumerate(comments_list):
                            st.markdown(f"**Comment {ci+1}:** {comment}")
        else:
            st.info("No evidence posts linked to this problem")

        # ── Section 3: Score History Table ───────────────────────
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
