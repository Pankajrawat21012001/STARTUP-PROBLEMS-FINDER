"""
Reddit Problem Discovery Pipeline — Orchestrator

Run with: python main.py
Runs all 5 steps in sequence. Safe to re-run anytime — deduplication prevents reprocessing.
"""

import os
import sys
import json
import time
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from steps.utils import (
    load_csv, save_csv, get_existing_post_ids,
    RAW_POSTS_COLUMNS, PROBLEM_IDS_COLUMNS,
    PROBLEM_EVIDENCE_COLUMNS, PROBLEM_SCORES_COLUMNS
)
from steps.step1_scrape import scrape_reddit
from steps.step2_noise_filter import filter_noise
from steps.step3_semantic_group import group_problems
from steps.step4_wtp_score import score_wtp
from steps.step5_groq_score import score_with_groq


# File paths
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")

RAW_POSTS_PATH = os.path.join(DATA_DIR, "raw_posts.csv")
PROBLEM_IDS_PATH = os.path.join(DATA_DIR, "problem_ids.csv")
PROBLEM_EVIDENCE_PATH = os.path.join(DATA_DIR, "problem_evidence.csv")
PROBLEM_SCORES_PATH = os.path.join(DATA_DIR, "problem_scores.csv")


def main():
    start_time = datetime.now()

    print("=" * 50)
    print("Reddit Problem Discovery Pipeline")
    print(f"Run started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # Load .env
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(env_path)

    # Verify API keys are set
    if not os.getenv("REDDIT_CLIENT_ID") or os.getenv("REDDIT_CLIENT_ID") == "your_reddit_client_id":
        print("\n✗ ERROR: Please set your Reddit API credentials in .env file")
        print("  Get credentials at: https://www.reddit.com/prefs/apps")
        sys.exit(1)

    if not os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY") == "your_groq_api_key":
        print("\n✗ ERROR: Please set your Groq API key in .env file")
        print("  Get key at: https://console.groq.com")
        sys.exit(1)

    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)

    # Load existing data
    raw_posts_df = load_csv(RAW_POSTS_PATH, RAW_POSTS_COLUMNS)
    problem_ids_df = load_csv(PROBLEM_IDS_PATH, PROBLEM_IDS_COLUMNS)
    problem_evidence_df = load_csv(PROBLEM_EVIDENCE_PATH, PROBLEM_EVIDENCE_COLUMNS)
    problem_scores_df = load_csv(PROBLEM_SCORES_PATH, PROBLEM_SCORES_COLUMNS)

    existing_post_ids = get_existing_post_ids(raw_posts_df)

    # Load config
    with open(os.path.join(CONFIG_DIR, "subreddits.json"), "r") as f:
        subreddits = json.load(f)
    with open(os.path.join(CONFIG_DIR, "search_phrases.json"), "r") as f:
        search_phrases = json.load(f)

    # Track summary stats
    summary = {
        "new_posts": 0,
        "passed_filter": 0,
        "mapped_existing": 0,
        "new_problems": 0,
        "problems_scored": 0
    }

    try:
        # ── Step 1: Scrape Reddit ──────────────────────────────────
        print(f"\n[Step 1] Scraping Reddit...")
        new_posts = scrape_reddit(subreddits, search_phrases, existing_post_ids)
        summary["new_posts"] = len(new_posts)

        # Append new posts to raw_posts_df (before noise filter, so all are saved)
        if new_posts:
            new_posts_df = pd.DataFrame(new_posts)
            raw_posts_df = pd.concat([raw_posts_df, new_posts_df], ignore_index=True)

        save_csv(raw_posts_df, RAW_POSTS_PATH)
        print(f"  → Saved to data/raw_posts.csv")

        # ── Step 2: Noise Filter ──────────────────────────────────
        print(f"\n[Step 2] Noise filtering...")
        filtered_posts = filter_noise(new_posts)
        summary["passed_filter"] = len(filtered_posts)

        # Update passed_noise_filter in raw_posts_df for failed posts
        if new_posts:
            for post in new_posts:
                mask = raw_posts_df["post_id"].astype(str) == str(post["post_id"])
                raw_posts_df.loc[mask, "passed_noise_filter"] = post.get("passed_noise_filter", False)
            save_csv(raw_posts_df, RAW_POSTS_PATH)

        # ── Step 3: Semantic Grouping ─────────────────────────────
        print(f"\n[Step 3] Semantic grouping...")
        problem_ids_before = len(problem_ids_df)
        problem_ids_df, problem_evidence_df = group_problems(
            filtered_posts, problem_ids_df, problem_evidence_df
        )
        summary["new_problems"] = len(problem_ids_df) - problem_ids_before
        summary["mapped_existing"] = len(filtered_posts) - summary["new_problems"]

        save_csv(problem_ids_df, PROBLEM_IDS_PATH)
        save_csv(problem_evidence_df, PROBLEM_EVIDENCE_PATH)
        print(f"  → Saved to data/problem_ids.csv and data/problem_evidence.csv")

        # ── Step 4: WTP Scoring ───────────────────────────────────
        print(f"\n[Step 4] WTP scoring...")
        problem_evidence_df, problem_ids_df = score_wtp(
            problem_evidence_df, raw_posts_df, problem_ids_df
        )

        save_csv(problem_evidence_df, PROBLEM_EVIDENCE_PATH)
        save_csv(problem_ids_df, PROBLEM_IDS_PATH)
        print(f"  → Saved to data/problem_evidence.csv")

        # ── Step 5: Groq Scoring ─────────────────────────────────
        print(f"\n[Step 5] Groq scoring...")
        problem_ids_df, problem_scores_df = score_with_groq(
            problem_ids_df, problem_evidence_df, raw_posts_df, problem_scores_df
        )

        save_csv(problem_scores_df, PROBLEM_SCORES_PATH)
        save_csv(problem_ids_df, PROBLEM_IDS_PATH)
        print(f"  → Saved to data/problem_scores.csv")

    except KeyboardInterrupt:
        print("\n\n⚠ Pipeline interrupted by user. Saving data...")
    except Exception as e:
        print(f"\n\n✗ Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        print("\nSaving data before exit...")
    finally:
        # Always save CSVs before exiting
        try:
            save_csv(raw_posts_df, RAW_POSTS_PATH)
            save_csv(problem_ids_df, PROBLEM_IDS_PATH)
            save_csv(problem_evidence_df, PROBLEM_EVIDENCE_PATH)
            save_csv(problem_scores_df, PROBLEM_SCORES_PATH)
        except Exception as save_err:
            print(f"  ✗ Error saving CSVs: {save_err}")

    # ── Summary ──────────────────────────────────────────────────
    end_time = datetime.now()
    elapsed = end_time - start_time
    minutes = int(elapsed.total_seconds() // 60)
    seconds = int(elapsed.total_seconds() % 60)

    print(f"\n{'=' * 50}")
    print(f"Run complete: {end_time.strftime('%Y-%m-%d %H:%M:%S')} ({minutes}m {seconds}s)")

    # Show top 3 problems
    if not problem_ids_df.empty and "latest_final_rank_score" in problem_ids_df.columns:
        scored = problem_ids_df.dropna(subset=["latest_final_rank_score"])
        if not scored.empty:
            top3 = scored.nlargest(3, "latest_final_rank_score")
            print("Top 3 problems this run:")
            for rank, (_, row) in enumerate(top3.iterrows(), 1):
                score = row["latest_final_rank_score"]
                name = row["problem_name"]
                print(f"  #{rank}  {name:<50} [{score}/100]")

    print(f"Run dashboard: streamlit run dashboard.py")
    print("=" * 50)


if __name__ == "__main__":
    main()
