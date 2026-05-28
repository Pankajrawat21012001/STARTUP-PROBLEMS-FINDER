"""
Step 5: Groq API scoring.

Sends qualifying problems to Groq for 8-factor evaluation.
Calculates total_score, freshness_weight, and final_rank_score.
"""

import os
import json
import time
from datetime import datetime, date, timedelta

import pandas as pd

from .utils import next_id
from .step4_wtp_score import WTP_PHRASES, URGENCY_PHRASES


def _calculate_freshness_weight(last_seen_date_str):
    """Calculate freshness weight based on last_seen_date."""
    try:
        if pd.isna(last_seen_date_str) or not last_seen_date_str:
            return 0.6
        last_seen = datetime.strptime(str(last_seen_date_str)[:10], "%Y-%m-%d").date()
        days_ago = (date.today() - last_seen).days

        if days_ago <= 7:
            return 1.0
        elif days_ago <= 14:
            return 0.9
        elif days_ago <= 30:
            return 0.8
        else:
            return 0.6
    except Exception:
        return 0.6


def _compute_wtp_score(evidence_posts_df):
    """
    Calculate average WTP score across all evidence posts for a problem.
    """
    if evidence_posts_df.empty:
        return 0.0

    scores = []
    for _, post in evidence_posts_df.iterrows():
        title = str(post.get("title", ""))
        body = str(post.get("body", ""))
        top_comments = str(post.get("top_comments", ""))

        full_text = f"{title} {body} {top_comments}".lower()

        wtp_count = 0
        for phrase in WTP_PHRASES:
            if phrase in full_text:
                wtp_count += 1
        wtp_score = min(wtp_count, 3)
        scores.append(wtp_score)

    if not scores:
        return 0.0

    return round(sum(scores) / len(scores), 2)


def score_with_groq(problem_ids_df, problem_evidence_df, raw_posts_df, problem_scores_df):
    """
    Score qualifying problems using Groq API.

    Qualifying criteria:
    - evidence_count >= 3
    - avg_wtp_score >= 1.0
    - Not already scored today

    Args:
        problem_ids_df: problems DataFrame
        problem_evidence_df: evidence DataFrame
        raw_posts_df: raw posts DataFrame
        problem_scores_df: existing scores DataFrame

    Returns:
        tuple of (updated_problem_ids_df, updated_problem_scores_df)
    """
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    today = date.today().isoformat()

    # Find qualifying problems
    qualifying = problem_ids_df[
        problem_ids_df["evidence_count"].astype(float) >= 1
    ].copy()

    # Exclude problems already scored today
    if not problem_scores_df.empty:
        scored_today = problem_scores_df[
            problem_scores_df["run_date"].astype(str) == today
        ]["problem_id"].tolist()
        qualifying = qualifying[~qualifying["problem_id"].isin(scored_today)]

    if qualifying.empty:
        print("  -> No problems qualify for scoring (need evidence >= 1)")
        return problem_ids_df, problem_scores_df

    print(f"  -> {len(qualifying)} problems qualify for scoring (evidence >= 1)")

    scored_count = 0

    for i, (idx, problem) in enumerate(qualifying.iterrows()):
        problem_id = problem["problem_id"]
        problem_name = problem["problem_name"]
        industry = problem["industry"]

        print(f"  -> Scoring problem {i+1}/{len(qualifying)}: \"{problem_name}\"")

        # Gather evidence posts
        evidence_rows = problem_evidence_df[
            problem_evidence_df["problem_id"] == problem_id
        ]
        evidence_post_ids = evidence_rows["post_id"].astype(str).tolist()

        evidence_posts = raw_posts_df[
            raw_posts_df["post_id"].astype(str).isin(evidence_post_ids)
        ]

        # Build evidence text (truncated to 3000 chars)
        evidence_texts = []
        total_chars = 0
        for _, post in evidence_posts.iterrows():
            text = f"Title: {post['title']}\nBody: {str(post['body'])[:300]}\n---"
            if total_chars + len(text) > 3000:
                break
            evidence_texts.append(text)
            total_chars += len(text)

        evidence_text = "\n".join(evidence_texts)

        # Build Groq prompt
        prompt = f"""You are a startup idea evaluator. Evaluate the following problem based on evidence from Reddit posts.

Problem name: {problem_name}
Industry: {industry}

Evidence posts:
{evidence_text}

Score each factor from 1–10. Return ONLY a JSON object with no explanation:
{{
  "problem_acuteness": <1-10, how painful and frequent is this problem>,
  "customer_clarity": <1-10, how clearly defined is the target customer>,
  "market_size": <1-10, how large is the addressable market>,
  "competition": <1-10, how low is existing competition — 10 means almost no competition>,
  "good_ideaspace": <1-10, how promising is this SaaS category>,
  "real_problem": <1-10, how real and validated is this problem>,
  "tarpit_risk": <1-10, how low is the risk this is an unsolvable tarpit — 10 means not a tarpit>,
  "good_proxies": <1-10, how many successful companies have proven adjacent ideas>
}}"""

        # Call Groq API
        wtp_score = _compute_wtp_score(evidence_posts)
        scores = _call_groq_for_scores(client, prompt)
        if scores is None:
            print(f"  [!] Failed to score \"{problem_name}\", skipping")
            continue

        # Calculate total and final scores
        factor_keys = [
            "problem_acuteness", "customer_clarity", "market_size", "competition",
            "good_ideaspace", "real_problem", "tarpit_risk", "good_proxies"
        ]
        total_score = sum(scores.get(k, 5) for k in factor_keys)
        freshness_weight = _calculate_freshness_weight(problem.get("last_seen_date"))
        final_rank_score = round((total_score / 80 * 100) * freshness_weight, 1)

        # Append to problem_scores_df
        score_id = next_id(problem_scores_df, "id")
        new_score_row = {
            "id": score_id,
            "problem_id": problem_id,
            "run_date": today,
            "wtp_score": wtp_score,
            **{k: scores.get(k, 5) for k in factor_keys},
            "total_score": total_score,
            "freshness_weight": freshness_weight,
            "final_rank_score": final_rank_score
        }
        problem_scores_df = pd.concat(
            [problem_scores_df, pd.DataFrame([new_score_row])],
            ignore_index=True
        )

        # Update problem_ids_df
        problem_ids_df["latest_total_score"] = pd.to_numeric(problem_ids_df["latest_total_score"], errors="coerce")
        problem_ids_df["latest_final_rank_score"] = pd.to_numeric(problem_ids_df["latest_final_rank_score"], errors="coerce")
        pid_mask = problem_ids_df["problem_id"] == problem_id
        if pid_mask.any():
            problem_ids_df.loc[pid_mask, "latest_total_score"] = total_score
            problem_ids_df.loc[pid_mask, "latest_final_rank_score"] = final_rank_score

        scored_count += 1

        # Rate limit
        time.sleep(0.5)

    print(f"  -> {scored_count} problems scored")

    return problem_ids_df, problem_scores_df


def _call_groq_for_scores(client, prompt):
    """Call Groq API and parse JSON response. Retries once on failure."""
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300
            )
            content = response.choices[0].message.content.strip()

            # Handle markdown code blocks
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            scores = json.loads(content)

            # Validate all scores are integers 1–10
            factor_keys = [
                "problem_acuteness", "customer_clarity", "market_size", "competition",
                "good_ideaspace", "real_problem", "tarpit_risk", "good_proxies"
            ]
            for key in factor_keys:
                val = scores.get(key, 5)
                scores[key] = max(1, min(10, int(val)))

            return scores

        except Exception as e:
            if attempt == 0:
                print(f"  [!] Groq parse error (retrying): {e}")
                time.sleep(1)
            else:
                print(f"  [x] Groq scoring failed after retry: {e}")
                return None

    return None
