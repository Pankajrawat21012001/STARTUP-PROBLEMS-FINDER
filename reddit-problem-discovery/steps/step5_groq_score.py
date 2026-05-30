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
        
        date_str = str(last_seen_date_str)[:10]
        try:
            last_seen = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            last_seen = datetime.strptime(date_str, "%d-%m-%Y").date()
            
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


def score_with_groq(problem_ids_df, problem_evidence_df, raw_posts_df, problem_scores_df, is_resume=False, run_timestamp=None):
    """
    Score qualifying problems using Groq API.

    Qualifying criteria:
    - evidence_count >= 3
    - avg_wtp_score >= 1.0
    - Not already scored today (or not scored at all if is_resume=True)

    Args:
        problem_ids_df: problems DataFrame
        problem_evidence_df: evidence DataFrame
        raw_posts_df: raw posts DataFrame
        problem_scores_df: existing scores DataFrame
        is_resume: whether we are resuming unscored problems
        run_timestamp: exact pipeline completion time string

    Returns:
        tuple of (updated_problem_ids_df, updated_problem_scores_df)
    """
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    today = date.today().isoformat()
    if run_timestamp is None:
        run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Find qualifying problems
    qualifying = problem_ids_df[
        problem_ids_df["evidence_count"].astype(float) >= 1
    ].copy()

    # Skip problems manually rejected in the dashboard
    reviews_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "data", "idea_reviews.csv")
    if os.path.exists(reviews_path):
        try:
            reviews = pd.read_csv(reviews_path)
            rejected_ids = reviews[reviews["status"] == "Rejected"]["problem_id"].tolist()
            qualifying = qualifying[~qualifying["problem_id"].isin(rejected_ids)]
        except Exception:
            pass

    # Exclude problems already scored
    if not problem_scores_df.empty:
        if is_resume:
            scored_ids = problem_scores_df["problem_id"].tolist()
            qualifying = qualifying[~qualifying["problem_id"].isin(scored_ids)]
        else:
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
            text = f"Title: {post['title']}\nBody: {str(post['body'])[:600]}\n---"
            if total_chars + len(text) > 3000:
                break
            evidence_texts.append(text)
            total_chars += len(text)

        evidence_text = "\n".join(evidence_texts)

        # Build Groq prompt
        prompt = f"""You are a ruthless, skeptical startup idea evaluator. Your job is to KILL bad ideas.
                    Most problems score 3-5. Only award 7+ if there is EXPLICIT evidence in the Reddit posts below.

                    Problem: {problem_name}
                    Industry: {industry}

                    Reddit Evidence ({len(evidence_texts)} posts):
                    {evidence_text}

                    SCORING RULES — be harsh:
                    - Base every score on WHAT IS ACTUALLY WRITTEN in the evidence above.
                    - If you cannot find direct evidence for a high score, score it LOW (3-4).
                    - Do not invent signals that are not in the text.
                    - A single Reddit post with under 20 upvotes = very weak signal. Score accordingly.
                    - Generic complaints like "this is hard" = 3. Specific workflow + dollar value + frequency = 8+.

                    Factor-by-factor guide:
                    - problem_acuteness (1-10): Daily bleeding wound vs occasional annoyance.
                    EVIDENCE REQUIRED: words like "every day", "waste hours weekly", "nightmare", specific time lost.
                    1 post with vague complaint = max 4. Multiple posts with specific workflows = 7+.
                    
                    - customer_clarity (1-10): Can you name the buyer's exact job title AND company type?
                    "renters in Bangalore" = 3 (huge segment, no B2B clarity). "GST-registered freelance
                    consultants in India billing US clients" = 9.

                    - market_size (1-10): TAM signals. India city-specific = max 4. India-wide B2B = 6.
                    Global SaaS market = 8+. Only score 9-10 with explicit market references.

                    - competition (1-10): 10 = truly no tool exists. 5 = weak tools exist. 1 = Salesforce owns this.
                    If evidence doesn't mention existing tools AT ALL, default to 5 (unknown, not blue ocean).

                    - good_ideaspace (1-10): Platform with 5+ expansion paths = 8+. Single narrow feature = 2.

                    - real_problem (1-10): Specific Reddit workflow described = 8. "Someone should build X" = 4.
                    Emotional venting without workflow details = 3.

                    - tarpit_risk (1-10): 10 = genuinely novel. 1 = "blockchain + X" or idea pitched 1000 times.
                    If you don't have strong evidence of novelty, default 5.

                    - good_proxies (1-10): Named VC-backed adjacent companies = 8+. Vague "companies exist" = 4.
                    No named proxies in evidence = 3.

                    Return ONLY a JSON object, no explanation, no markdown:
                    {{
                    "problem_acuteness": <1-10>,
                    "customer_clarity": <1-10>,
                    "market_size": <1-10>,
                    "competition": <1-10>,
                    "good_ideaspace": <1-10>,
                    "real_problem": <1-10>,
                    "tarpit_risk": <1-10>,
                    "good_proxies": <1-10>
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
        problem_ids_df["avg_wtp_score"] = pd.to_numeric(problem_ids_df.get("avg_wtp_score", 0), errors="coerce")
        pid_mask = problem_ids_df["problem_id"] == problem_id
        if pid_mask.any():
            problem_ids_df.loc[pid_mask, "latest_total_score"] = total_score
            problem_ids_df.loc[pid_mask, "latest_final_rank_score"] = final_rank_score
            problem_ids_df.loc[pid_mask, "avg_wtp_score"] = wtp_score
            problem_ids_df.loc[pid_mask, "last_run_timestamp"] = run_timestamp

        scored_count += 1

        # Take a safe pause to avoid hitting rate limits
        time.sleep(2.0)

    print(f"  -> {scored_count} problems scored")

    return problem_ids_df, problem_scores_df


import re

def parse_groq_wait_time(err_msg):
    """
    Parses wait duration strings like '1m34.176s', '12m16.992s', '13m18.336s', '15s', or '1h2m3s'
    from Groq 429 rate limit exception strings and returns total seconds.
    """
    match = re.search(r"Please try again in\s+([^\s]+)", err_msg)
    if not match:
        return None
    time_str = match.group(1).rstrip('.')
    
    # Check for hours, minutes, seconds
    h_m = re.match(r"(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", time_str)
    if not h_m:
        return None
    
    hours = int(h_m.group(1)) if h_m.group(1) else 0
    minutes = int(h_m.group(2)) if h_m.group(2) else 0
    seconds = float(h_m.group(3)) if h_m.group(3) else 0.0
    
    total_seconds = hours * 3600 + minutes * 60 + seconds
    return total_seconds


def _call_groq_api_with_retry(client, prompt, model="llama-3.3-70b-versatile", temperature=0.1, max_tokens=300):
    """
    Calls Groq chat completions API with robust handling for 429 rate limits and general retries.
    Retries up to 5 times.
    """
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens
            )
            content = response.choices[0].message.content.strip()
            return content
        except Exception as e:
            err_msg = str(e)
            is_429 = "429" in err_msg or "rate_limit_exceeded" in err_msg.lower()
            
            if attempt == max_attempts:
                print(f"  [x] Groq call failed permanently after {max_attempts} attempts: {e}")
                return None
            
            if is_429:
                wait_time = parse_groq_wait_time(err_msg)
                if wait_time is not None:
                    sleep_duration = wait_time + 5.0
                    print(f"  [!] Groq Rate Limit (429) hit. Requested wait: {wait_time}s. Sleeping for {sleep_duration:.2f}s (with safety buffer) before retry (Attempt {attempt}/{max_attempts})...")
                else:
                    sleep_duration = 10.0 * attempt
                    print(f"  [!] Groq Rate Limit (429) hit but wait time unparseable. Sleeping for {sleep_duration}s before retry (Attempt {attempt}/{max_attempts})...")
                time.sleep(sleep_duration)
            else:
                sleep_duration = 5.0 * attempt
                print(f"  [!] Groq API error: {e}. Sleeping for {sleep_duration}s before retry (Attempt {attempt}/{max_attempts})...")
                time.sleep(sleep_duration)
                
    return None


def _call_groq_for_scores(client, prompt):
    """Call Groq API and parse JSON response. Retries using the robust helper."""
    content = _call_groq_api_with_retry(
        client, prompt, model="llama-3.3-70b-versatile", temperature=0.1, max_tokens=300
    )
    if content is None:
        return None
    try:
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
    except Exception as parse_err:
        print(f"  [x] Failed to parse scores JSON from response: {parse_err}. Content was: {content}")
        return None


# ── IDEA EVALUATION TABLE (new addition) ────────────────────────────────

IDEA_EVALUATION_COLUMNS = ["id", "problem_id", "run_date", "evaluation_json"]

EVALUATION_DIMENSIONS = [
    {
        "key": "problem_need",
        "category": "Problem & Need (Acute Problem)",
        "question": "Is it painful enough to pay for? Vitamin or Painkiller?"
    },
    {
        "key": "customer_clarity",
        "category": "Customer Clarity",
        "question": "Can the target user be clearly described? Do they have WTP now?"
    },
    {
        "key": "market_size",
        "category": "Market Size (Enough?)",
        "question": "Are people searching for this? Is the market growing and large enough?"
    },
    {
        "key": "competition",
        "category": "Competition",
        "question": "Who are competitors? Why will customers choose this over them?"
    },
    {
        "key": "demand_validation",
        "category": "Do People Want This?",
        "question": "Are there organic demand signals, workarounds, or communities proving demand?"
    },
    {
        "key": "recently_possible",
        "category": "Recently Possible",
        "question": "What tech, behavior, or market shift makes this possible or urgent now?"
    },
    {
        "key": "good_proxies",
        "category": "Good Proxies",
        "question": "Have adjacent companies proven this market? Strong demand proxies exist?"
    },
    {
        "key": "ideaspace",
        "category": "Good Ideaspace",
        "question": "Strong SaaS category with multiple expansion paths, or single narrow feature?"
    },
    {
        "key": "real_problem",
        "category": "Is It a Real Problem?",
        "question": "Genuine validated problem or a solution searching for a problem?"
    },
    {
        "key": "tarpit_risk",
        "category": "Tarpit Idea",
        "question": "Have many tried and failed here? Why would this attempt succeed?"
    }
]


def generate_idea_evaluation_table(
    problem_ids_df, problem_evidence_df, raw_posts_df, idea_evaluation_df, is_resume=False, run_timestamp=None
):
    """
    NEW: Generate a 10-dimension qualitative evaluation table for each problem using Groq.
    Saves results as JSON string to idea_evaluation.csv.
    Runs after score_with_groq() — qualifies problems with evidence_count >= 1.
    Skips problems already evaluated today (or not evaluated at all if is_resume=True).
    """
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    today = date.today().isoformat()
    if run_timestamp is None:
        run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    qualifying = problem_ids_df[
        problem_ids_df["evidence_count"].astype(float) >= 1
    ].copy()

    # Skip problems manually rejected in the dashboard
    reviews_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "data", "idea_reviews.csv")
    if os.path.exists(reviews_path):
        try:
            reviews = pd.read_csv(reviews_path)
            rejected_ids = reviews[reviews["status"] == "Rejected"]["problem_id"].tolist()
            qualifying = qualifying[~qualifying["problem_id"].isin(rejected_ids)]
        except Exception:
            pass

    if not idea_evaluation_df.empty and "problem_id" in idea_evaluation_df.columns:
        if is_resume:
            evaluated_ids = idea_evaluation_df["problem_id"].tolist()
            qualifying = qualifying[~qualifying["problem_id"].isin(evaluated_ids)]
        else:
            evaluated_today = idea_evaluation_df[
                idea_evaluation_df["run_date"].astype(str) == today
            ]["problem_id"].tolist()
            qualifying = qualifying[~qualifying["problem_id"].isin(evaluated_today)]

    if qualifying.empty:
        print("  -> No problems qualify for idea evaluation (already done today or no evidence)")
        return idea_evaluation_df

    print(f"  -> {len(qualifying)} problems queued for idea evaluation table")

    for i, (idx, problem) in enumerate(qualifying.iterrows()):
        problem_id   = problem["problem_id"]
        problem_name = problem["problem_name"]
        industry     = problem["industry"]

        print(f"  -> Evaluating {i+1}/{len(qualifying)}: \"{problem_name}\"")

        evidence_rows     = problem_evidence_df[problem_evidence_df["problem_id"] == problem_id]
        evidence_post_ids = evidence_rows["post_id"].astype(str).tolist()
        evidence_posts    = raw_posts_df[raw_posts_df["post_id"].astype(str).isin(evidence_post_ids)]

        evidence_texts, total_chars = [], 0
        for _, post in evidence_posts.iterrows():
            text = f"Title: {post['title']}\nBody: {str(post['body'])[:600]}\n---"
            if total_chars + len(text) > 3000:
                break
            evidence_texts.append(text)
            total_chars += len(text)
        evidence_text = "\n".join(evidence_texts)

        dim_lines = "\n".join(
            f"{j+1}. {d['category']}: {d['question']}"
            for j, d in enumerate(EVALUATION_DIMENSIONS)
        )
        json_template = "\n".join(
            f'  "{d["key"]}": {{"verdict": "PASS or WARN or FAIL", "answer": "2-4 sentence specific analysis"}}'
            for d in EVALUATION_DIMENSIONS
        )

        prompt = f"""You are a ruthless startup idea evaluator. Evaluate this problem across 
10 dimensions using the Reddit evidence below as your primary signal.

Problem: {problem_name}
Industry: {industry}

Reddit Evidence:
{evidence_text}

Dimensions to evaluate:
{dim_lines}

For each dimension return:
- verdict: "PASS" (strong positive), "WARN" (mixed/uncertain), or "FAIL" (clear red flag)
- answer: 2-4 specific opinionated sentences referencing the Reddit evidence where possible.
  Be direct. No hedging. Call out exact failure modes or strengths.

Return ONLY valid JSON, no markdown, no preamble:
{{
{json_template}
}}"""

        content = _call_groq_api_with_retry(
            client, prompt, model="llama-3.3-70b-versatile", temperature=0.15, max_tokens=2000
        )
        if content is None:
            continue

        try:
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            evaluation = json.loads(content)
            valid = {"PASS", "WARN", "FAIL"}
            for d in EVALUATION_DIMENSIONS:
                k = d["key"]
                if k in evaluation and isinstance(evaluation[k], dict):
                    v = str(evaluation[k].get("verdict", "WARN")).upper()
                    evaluation[k]["verdict"] = v if v in valid else "WARN"
        except Exception as parse_err:
            print(f"  [x] Failed to parse evaluation JSON for \"{problem_name}\": {parse_err}")
            continue

        existing_ids = pd.to_numeric(
            idea_evaluation_df.get("id", pd.Series()), errors="coerce"
        ).dropna()
        new_id = int(existing_ids.max()) + 1 if not existing_ids.empty else 1

        idea_evaluation_df = pd.concat([
            idea_evaluation_df,
            pd.DataFrame([{
                "id": new_id,
                "problem_id": problem_id,
                "run_date": today,
                "evaluation_json": json.dumps(evaluation)
            }])
        ], ignore_index=True)

        # Update last_run_timestamp in problem_ids_df
        pid_mask = problem_ids_df["problem_id"] == problem_id
        if pid_mask.any():
            problem_ids_df.loc[pid_mask, "last_run_timestamp"] = run_timestamp

        # Take a safe pause to avoid hitting rate limits
        time.sleep(2.0)

    return idea_evaluation_df

