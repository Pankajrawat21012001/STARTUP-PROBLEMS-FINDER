"""
Step 4: Willingness-to-Pay (WTP) scoring.

Scans evidence posts for WTP and urgency phrases,
scores each evidence row 0–3, and updates problem-level avg_wtp_score.
"""

import pandas as pd

# WTP phrases — each match adds +1, capped at 3
WTP_PHRASES = [
    "would pay", "i'd pay", "willing to pay", "worth paying",
    "subscription", "enterprise plan", "our company would", "budget for",
    "paying for", "charge for this", "affordable tool", "worth the money",
    "would buy", "need to purchase"
]

# Urgency phrases — collected as matched keywords
URGENCY_PHRASES = [
    "urgent", "critical", "costing us", "losing money", "hours wasted",
    "every day", "daily problem", "manually every", "broken process",
    "nightmare", "so frustrated", "desperately need"
]


def score_wtp(evidence_df, raw_posts_df, problem_ids_df):
    """
    Score willingness-to-pay for each evidence row.
    NOTE: This function is no longer called from main.py, as WTP scoring is now
    folded directly into Step 5 (Groq scoring). Keep this file for its constants.

    Args:
        evidence_df: problem_evidence DataFrame
        raw_posts_df: raw_posts DataFrame
        problem_ids_df: problem_ids DataFrame

    Returns:
        tuple of (updated_evidence_df, updated_problem_ids_df)
    """
    if evidence_df.empty:
        print("  -> No evidence rows to score")
        return evidence_df, problem_ids_df

    scored_count = 0

    for idx, row in evidence_df.iterrows():
        post_id = str(row["post_id"])

        # Find the matching raw post
        post_match = raw_posts_df[raw_posts_df["post_id"].astype(str) == post_id]
        if post_match.empty:
            continue

        post = post_match.iloc[0]

        # Build full text for analysis
        full_text = " ".join([
            str(post.get("title", "")),
            str(post.get("body", "")),
            str(post.get("top_comments", ""))
        ]).lower()

        # Score WTP phrases (count matches, cap at 3)
        wtp_count = 0
        for phrase in WTP_PHRASES:
            if phrase in full_text:
                wtp_count += 1
        wtp_score = min(wtp_count, 3)

        # Collect urgency keywords
        matched_urgency = []
        for phrase in URGENCY_PHRASES:
            if phrase in full_text:
                matched_urgency.append(phrase)

        # Update evidence row
        evidence_df.at[idx, "wtp_score"] = wtp_score
        evidence_df.at[idx, "urgency_keywords"] = ", ".join(matched_urgency)
        scored_count += 1

    # Recalculate avg_wtp_score per problem
    for idx, row in problem_ids_df.iterrows():
        pid = row["problem_id"]
        problem_evidence = evidence_df[evidence_df["problem_id"] == pid]
        if not problem_evidence.empty:
            avg_wtp = round(problem_evidence["wtp_score"].astype(float).mean(), 2)
            problem_ids_df.at[idx, "avg_wtp_score"] = avg_wtp

    avg_overall = round(evidence_df["wtp_score"].astype(float).mean(), 1) if not evidence_df.empty else 0.0

    print(f"  -> {scored_count} evidence rows scored for WTP")
    print(f"  -> Average WTP score: {avg_overall} / 3.0")

    return evidence_df, problem_ids_df
