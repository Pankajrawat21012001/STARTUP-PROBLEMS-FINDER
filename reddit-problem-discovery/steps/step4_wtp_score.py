"""
Step 4: Willingness-to-Pay (WTP) scoring.

Scans evidence posts for WTP and urgency phrases,
scores each evidence row 0–3, and updates problem-level avg_wtp_score.
"""

import pandas as pd

# WTP phrases — each match adds +1, capped at 3
WTP_PHRASES = [
    # Original phrases
    "would pay", "i'd pay", "willing to pay", "worth paying",
    "subscription", "enterprise plan", "our company would", "budget for",
    "paying for", "charge for this", "affordable tool", "worth the money",
    "would buy", "need to purchase",
    # Conversational/Reddit additions
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

# Urgency phrases — collected as matched keywords
URGENCY_PHRASES = [
    # Original phrases
    "urgent", "critical", "costing us", "losing money", "hours wasted",
    "every day", "daily problem", "manually every", "broken process",
    "nightmare", "so frustrated", "desperately need",
    # Additions
    "massive pain", "huge problem", "real pain point",
    "huge time sink", "takes forever", "kills productivity",
    "inefficient", "waste of time", "painful process",
    "no solution", "workaround", "band-aid solution",
    "fed up", "sick of", "really annoying",
    "tedious", "repetitive task", "manual work",
    "this is ridiculous", "why is this so hard",
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
    problem_ids_df["avg_wtp_score"] = pd.to_numeric(problem_ids_df["avg_wtp_score"], errors="coerce").fillna(0.0)
    for idx, row in problem_ids_df.iterrows():
        pid = row["problem_id"]
        problem_evidence = evidence_df[evidence_df["problem_id"] == pid]
        if not problem_evidence.empty:
            avg_wtp = round(pd.to_numeric(problem_evidence["wtp_score"], errors="coerce").fillna(0).mean(), 2)
            problem_ids_df.loc[idx, "avg_wtp_score"] = avg_wtp

    avg_overall = round(evidence_df["wtp_score"].astype(float).mean(), 1) if not evidence_df.empty else 0.0

    print(f"  -> {scored_count} evidence rows scored for WTP")
    print(f"  -> Average WTP score: {avg_overall} / 3.0")

    return evidence_df, problem_ids_df
