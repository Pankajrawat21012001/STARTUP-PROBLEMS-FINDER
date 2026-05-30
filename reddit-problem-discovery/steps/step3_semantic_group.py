"""
Step 3: Semantic grouping using sentence-transformers.

Groups filtered posts into problems using cosine similarity.
Creates new problems via Groq when no existing match is found.
"""

import os
import uuid
import json
import time
from datetime import datetime, date

import pandas as pd
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from .utils import next_id

# Similarity threshold for grouping posts into existing problems
SIMILARITY_THRESHOLD = 0.78


def _normalize_date(date_str):
    """Normalize dd-mm-yyyy to yyyy-mm-dd for proper sorting."""
    date_str = str(date_str).strip()[:10]
    parts = date_str.split('-')
    if len(parts) == 3 and len(parts[0]) == 2 and len(parts[2]) == 4:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str


def _load_model():
    """Load sentence-transformers model with caching."""
    try:
        from sentence_transformers import SentenceTransformer
        print("  -> Loading model: all-MiniLM-L6-v2")
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model
    except ImportError:
        print("  [!] sentence-transformers not installed!")
        print("    Run: pip install sentence-transformers")
        raise
    except Exception as e:
        print(f"  [!] Failed to load model: {e}")
        print("    Make sure sentence-transformers is installed: pip install sentence-transformers")
        raise


def _generate_problem_name(post_title, post_body, groq_client):
    """Use Groq to generate a short problem name and industry tag."""
    prompt = (
        "Given this Reddit post, extract:\n"
        "1) A short problem name (max 10 words, describe the core SaaS-solvable problem)\n"
        "2) Industry category (one of: HR SaaS, EdTech, Fintech, LegalTech, HealthTech, "
        "LogisticsTech, MarketingTech, DevTools, OperationsSaaS, Other)\n\n"
        f"Post title: {post_title}\n"
        f"Post body: {post_body[:500]}\n\n"
        'Return only JSON: {"problem_name": "...", "industry": "..."}'
    )

    import re

    def parse_wait_time(err_msg):
        match = re.search(r"Please try again in\s+([^\s]+)", err_msg)
        if not match:
            return None
        time_str = match.group(1).rstrip('.')
        h_m = re.match(r"(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", time_str)
        if not h_m:
            return None
        hours = int(h_m.group(1)) if h_m.group(1) else 0
        minutes = int(h_m.group(2)) if h_m.group(2) else 0
        seconds = float(h_m.group(3)) if h_m.group(3) else 0.0
        return hours * 3600 + minutes * 60 + seconds

    content = None
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=150
            )
            content = response.choices[0].message.content.strip()
            break
        except Exception as e:
            err_msg = str(e)
            is_429 = "429" in err_msg or "rate_limit_exceeded" in err_msg.lower()
            
            if attempt == max_attempts:
                print(f"  [x] Groq call failed permanently in step3 after {max_attempts} attempts: {e}")
                break
            
            if is_429:
                wait_time = parse_wait_time(err_msg)
                if wait_time is not None:
                    sleep_duration = wait_time + 5.0
                    print(f"  [!] Groq Rate Limit (429) hit in step3. Sleeping for {sleep_duration:.2f}s before retry (Attempt {attempt}/{max_attempts})...")
                else:
                    sleep_duration = 10.0 * attempt
                    print(f"  [!] Groq Rate Limit (429) hit in step3. Sleeping for {sleep_duration}s before retry (Attempt {attempt}/{max_attempts})...")
                time.sleep(sleep_duration)
            else:
                sleep_duration = 5.0 * attempt
                print(f"  [!] Groq API error in step3: {e}. Sleeping for {sleep_duration}s before retry (Attempt {attempt}/{max_attempts})...")
                time.sleep(sleep_duration)

    if not content:
        # Fallback: use truncated title
        return post_title[:60], "Other"

    try:
        # Try to parse JSON from the response
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        problem_name = result.get("problem_name", "Unknown Problem")[:80]
        industry = result.get("industry", "Other")
        return problem_name, industry
    except Exception as parse_err:
        print(f"  [x] Failed to parse generated problem name JSON: {parse_err}. Content was: {content}")
        return post_title[:60], "Other"


def group_problems(filtered_posts, problem_ids_df, problem_evidence_df):
    """
    Group filtered posts into problems using semantic similarity.

    Args:
        filtered_posts: list of post dicts that passed noise filter
        problem_ids_df: existing problems DataFrame
        problem_evidence_df: existing evidence DataFrame

    Returns:
        tuple of (updated_problem_ids_df, updated_problem_evidence_df)
    """
    if not filtered_posts:
        print("  -> No posts to process")
        return problem_ids_df, problem_evidence_df

    # Load model
    model = _load_model()

    # Initialize Groq client for naming new problems
    from groq import Groq
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    # Build embeddings for existing problems
    existing_embeddings = None
    existing_problem_ids = []

    if not problem_ids_df.empty:
        existing_texts = (
            problem_ids_df["problem_name"].astype(str) + " " +
            problem_ids_df["industry"].astype(str)
        ).tolist()
        existing_embeddings = model.encode(existing_texts, show_progress_bar=False)
        existing_problem_ids = problem_ids_df["problem_id"].tolist()

    # Process each filtered post
    mapped_to_existing = 0
    new_problems_created = 0
    today = date.today().isoformat()

    print(f"  -> {len(filtered_posts)} posts processed")

    for post in filtered_posts:
        # Create embedding for this post
        post_text = str(post.get("title", "")) + " " + str(post.get("body", ""))[:500]
        post_embedding = model.encode([post_text], show_progress_bar=False)

        best_similarity = 0.0
        best_problem_id = None

        # Compare against existing problem embeddings
        if existing_embeddings is not None and len(existing_embeddings) > 0:
            similarities = cosine_similarity(post_embedding, existing_embeddings)[0]
            best_idx = np.argmax(similarities)
            best_similarity = float(similarities[best_idx])

            if best_similarity >= SIMILARITY_THRESHOLD:
                best_problem_id = existing_problem_ids[best_idx]

        if best_problem_id is not None:
            # Map to existing problem
            mapped_to_existing += 1
        else:
            # Create new problem
            problem_name, industry = _generate_problem_name(
                post.get("title", ""), post.get("body", ""), groq_client
            )
            # Take a safe pause to avoid hitting rate limits
            time.sleep(2.0)

            best_problem_id = str(uuid.uuid4())
            best_similarity = 1.0  # Self-match

            # Add new problem row
            new_problem = {
                "problem_id": best_problem_id,
                "problem_name": problem_name,
                "industry": industry,
                "first_seen_date": post.get("created_utc", today)[:10],
                "last_seen_date": post.get("created_utc", today)[:10],
                "evidence_count": 0,
                "avg_wtp_score": 0.0,
                "latest_total_score": None,
                "latest_final_rank_score": None
            }
            problem_ids_df = pd.concat(
                [problem_ids_df, pd.DataFrame([new_problem])],
                ignore_index=True
            )

            # Update embeddings for future comparisons in this run
            new_text = problem_name + " " + industry
            new_embedding = model.encode([new_text], show_progress_bar=False)
            if existing_embeddings is not None:
                existing_embeddings = np.vstack([existing_embeddings, new_embedding])
            else:
                existing_embeddings = new_embedding
            existing_problem_ids.append(best_problem_id)

            new_problems_created += 1

        # Add evidence row
        evidence_id = next_id(problem_evidence_df, "id")
        new_evidence = {
            "id": evidence_id,
            "problem_id": best_problem_id,
            "post_id": post["post_id"],
            "similarity_score": round(best_similarity, 4),
            "wtp_score": 0,  # Will be set in step 4
            "urgency_keywords": "",
            "post_created_date": post.get("created_utc", today)[:10],
            "added_date": today
        }
        problem_evidence_df = pd.concat(
            [problem_evidence_df, pd.DataFrame([new_evidence])],
            ignore_index=True
        )

    # Update evidence_count and last_seen_date for all problems
    for idx, row in problem_ids_df.iterrows():
        pid = row["problem_id"]
        evidence_for_problem = problem_evidence_df[problem_evidence_df["problem_id"] == pid]
        problem_ids_df.at[idx, "evidence_count"] = len(evidence_for_problem)

        if not evidence_for_problem.empty:
            dates = evidence_for_problem["post_created_date"].dropna()
            if not dates.empty:
                normalized_dates = dates.apply(_normalize_date)
                problem_ids_df.at[idx, "last_seen_date"] = normalized_dates.max()
                
                current_first = _normalize_date(row.get("first_seen_date", normalized_dates.min()))
                problem_ids_df.at[idx, "first_seen_date"] = min(current_first, normalized_dates.min())

    print(f"  -> {mapped_to_existing} posts mapped to existing problems")
    print(f"  -> {new_problems_created} new problems created")
    print(f"  -> Total problems tracked: {len(problem_ids_df)}")

    return problem_ids_df, problem_evidence_df
