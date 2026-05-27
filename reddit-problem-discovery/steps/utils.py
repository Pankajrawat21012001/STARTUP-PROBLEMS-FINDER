"""
Shared CSV utilities for the pipeline.
"""

import pandas as pd
import os


def load_csv(filepath, columns):
    """Load CSV or return empty DataFrame with given columns if file doesn't exist."""
    if os.path.exists(filepath):
        try:
            df = pd.read_csv(filepath, encoding="utf-8")
            # Verify columns match — if corrupted, recreate
            if list(df.columns) != columns:
                print(f"  [!] Column mismatch in {filepath}, recreating with correct schema")
                df = pd.DataFrame(columns=columns)
            return df
        except Exception as e:
            print(f"  [!] Error reading {filepath}: {e}")
            print(f"  -> Recreating with correct schema")
            return pd.DataFrame(columns=columns)
    return pd.DataFrame(columns=columns)


def save_csv(df, filepath):
    """Save DataFrame to CSV with UTF-8 encoding, index=False."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath, index=False, encoding="utf-8")


def get_existing_post_ids(raw_posts_df):
    """Return set of post_id strings for deduplication."""
    if raw_posts_df.empty:
        return set()
    return set(raw_posts_df["post_id"].astype(str).tolist())


def next_id(df, id_column):
    """Return max id + 1 for auto-increment columns."""
    if df.empty or id_column not in df.columns:
        return 1
    try:
        return int(df[id_column].max()) + 1
    except (ValueError, TypeError):
        return 1


# Column definitions for all CSV files
RAW_POSTS_COLUMNS = [
    "post_id", "title", "body", "top_comments", "subreddit", "upvotes",
    "comment_count", "post_url", "created_utc", "scraped_at", "passed_noise_filter"
]

PROBLEM_IDS_COLUMNS = [
    "problem_id", "problem_name", "industry", "first_seen_date", "last_seen_date",
    "evidence_count", "avg_wtp_score", "latest_total_score", "latest_final_rank_score"
]

PROBLEM_EVIDENCE_COLUMNS = [
    "id", "problem_id", "post_id", "similarity_score", "wtp_score",
    "urgency_keywords", "post_created_date", "added_date"
]

PROBLEM_SCORES_COLUMNS = [
    "id", "problem_id", "run_date", "wtp_score", "problem_acuteness", "customer_clarity",
    "market_size", "competition", "good_ideaspace", "real_problem",
    "tarpit_risk", "good_proxies", "total_score", "freshness_weight", "final_rank_score"
]
