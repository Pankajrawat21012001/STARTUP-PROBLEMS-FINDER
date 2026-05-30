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
from steps.step5_groq_score import score_with_groq, generate_idea_evaluation_table, IDEA_EVALUATION_COLUMNS


# File paths
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")

RAW_POSTS_PATH = os.path.join(DATA_DIR, "raw_posts.csv")
PROBLEM_IDS_PATH = os.path.join(DATA_DIR, "problem_ids.csv")
PROBLEM_EVIDENCE_PATH = os.path.join(DATA_DIR, "problem_evidence.csv")
PROBLEM_SCORES_PATH = os.path.join(DATA_DIR, "problem_scores.csv")
IDEA_EVALUATION_PATH = os.path.join(DATA_DIR, "idea_evaluation.csv")


def main():
    start_time = datetime.now()
    pipeline_run_timestamp = start_time.strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 50)
    print("Reddit Problem Discovery Pipeline")
    print(f"Run started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # Load .env
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(env_path)

    # Verify API keys are set
    if not os.getenv("SCRAPER_API_KEY") or os.getenv("SCRAPER_API_KEY") == "your_scraperapi_key":
        print("\n[x] ERROR: Please set your ScraperAPI key in .env file")
        print("  Get key at: https://dashboard.scraperapi.com")
        sys.exit(1)

    if not os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY") == "your_groq_api_key":
        print("\n[x] ERROR: Please set your Groq API key in .env file")
        print("  Get key at: https://console.groq.com")
        sys.exit(1)

    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)

    # Load existing data
    raw_posts_df = load_csv(RAW_POSTS_PATH, RAW_POSTS_COLUMNS)
    problem_ids_df = load_csv(PROBLEM_IDS_PATH, PROBLEM_IDS_COLUMNS)
    problem_evidence_df = load_csv(PROBLEM_EVIDENCE_PATH, PROBLEM_EVIDENCE_COLUMNS)
    problem_scores_df = load_csv(PROBLEM_SCORES_PATH, PROBLEM_SCORES_COLUMNS)
    idea_evaluation_df = load_csv(IDEA_EVALUATION_PATH, IDEA_EVALUATION_COLUMNS)

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
        # ── Check and Resume Pending Problems ──────────────────────
        if not problem_ids_df.empty:
            # Problems missing score
            missing_score_mask = (problem_ids_df["evidence_count"].astype(float) >= 1) & (
                (~problem_ids_df["problem_id"].isin(problem_scores_df["problem_id"])) | 
                (pd.isna(problem_ids_df["latest_final_rank_score"]))
            )
            
            # Problems missing evaluation
            missing_eval_mask = (problem_ids_df["evidence_count"].astype(float) >= 1) & (
                ~problem_ids_df["problem_id"].isin(idea_evaluation_df["problem_id"])
            )
            
            pending_score_ids = set(problem_ids_df[missing_score_mask]["problem_id"].tolist())
            pending_eval_ids = set(problem_ids_df[missing_eval_mask]["problem_id"].tolist())
            pending_ids = pending_score_ids.union(pending_eval_ids)
            
            # Exclude problems manually rejected in the dashboard
            reviews_path = os.path.join(DATA_DIR, "idea_reviews.csv")
            if os.path.exists(reviews_path) and pending_ids:
                try:
                    reviews = pd.read_csv(reviews_path)
                    rejected_ids = set(reviews[reviews["status"] == "Rejected"]["problem_id"].tolist())
                    pending_ids = pending_ids - rejected_ids
                except Exception:
                    pass

            if pending_ids:
                print("=" * 50)
                print(f"[!] RESUME CHECK: Found {len(pending_ids)} pending problems from previous runs")
                print(f"    - Missing scoring: {len(pending_score_ids)}")
                print(f"    - Missing evaluation: {len(pending_eval_ids)}")
                print("    Catching up these pending problems first...")
                print("=" * 50)
                
                pending_problems_df = problem_ids_df[problem_ids_df["problem_id"].isin(pending_ids)].copy()
                
                # 1. Run scoring on pending
                print(f"\n[Step 4 - Resume] Resuming Groq scoring for pending problems...")
                pending_problems_df, problem_scores_df = score_with_groq(
                    pending_problems_df, problem_evidence_df, raw_posts_df, problem_scores_df, is_resume=True, run_timestamp=pipeline_run_timestamp
                )
                save_csv(problem_scores_df, PROBLEM_SCORES_PATH)
                
                # Sync scoring back to master problem_ids_df
                if not problem_scores_df.empty:
                    latest_scores = problem_scores_df.sort_values("run_date").groupby("problem_id").last().reset_index()
                    for _, row in latest_scores.iterrows():
                        pid = row["problem_id"]
                        mask = problem_ids_df["problem_id"] == pid
                        if mask.any():
                            problem_ids_df.loc[mask, "latest_total_score"] = row["total_score"]
                            problem_ids_df.loc[mask, "latest_final_rank_score"] = row["final_rank_score"]
                            problem_ids_df.loc[mask, "avg_wtp_score"] = row["wtp_score"]

                # 2. Run evaluation table on pending
                print(f"\n[Step 5 - Resume] Resuming idea evaluation for pending problems...")
                idea_evaluation_df = generate_idea_evaluation_table(
                    pending_problems_df, problem_evidence_df, raw_posts_df, idea_evaluation_df, is_resume=True, run_timestamp=pipeline_run_timestamp
                )
                save_csv(idea_evaluation_df, IDEA_EVALUATION_PATH)

                # Sync last_run_timestamp and metadata back to master problem_ids_df
                for _, row in pending_problems_df.iterrows():
                    pid = row["problem_id"]
                    mask = problem_ids_df["problem_id"] == pid
                    if mask.any() and "last_run_timestamp" in pending_problems_df.columns:
                        val = row["last_run_timestamp"]
                        if pd.notna(val) and val:
                            problem_ids_df.loc[mask, "last_run_timestamp"] = val
                
                save_csv(problem_ids_df, PROBLEM_IDS_PATH)
                
                print("\n" + "=" * 50)
                print("[!] RESUME CHECK COMPLETE: Pending problems caught up successfully!")
                print("=" * 50 + "\n")

        # ── Step 1: Scrape Reddit ──────────────────────────────────
        print(f"\n[Step 1] Scraping Reddit...")
        new_posts = scrape_reddit(subreddits, search_phrases, existing_post_ids)
        summary["new_posts"] = len(new_posts)

        # Append new posts to raw_posts_df (before noise filter, so all are saved)
        if new_posts:
            new_posts_df = pd.DataFrame(new_posts)
            raw_posts_df = pd.concat([raw_posts_df, new_posts_df], ignore_index=True)

        save_csv(raw_posts_df, RAW_POSTS_PATH)
        print(f"  -> Saved to data/raw_posts.csv")

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
        print(f"  -> Saved to data/problem_ids.csv and data/problem_evidence.csv")

        # ── Step 4: Groq Scoring ─────────────────────────────────
        print(f"\n[Step 4] Groq scoring...")
        problem_ids_df, problem_scores_df = score_with_groq(
            problem_ids_df, problem_evidence_df, raw_posts_df, problem_scores_df, run_timestamp=pipeline_run_timestamp
        )

        save_csv(problem_scores_df, PROBLEM_SCORES_PATH)
        save_csv(problem_ids_df, PROBLEM_IDS_PATH)
        print(f"  -> Saved to data/problem_scores.csv")

        # ── Step 5: Idea Evaluation Table ──────────────────────
        print(f"\n[Step 5] Generating idea evaluation tables...")
        idea_evaluation_df = generate_idea_evaluation_table(
            problem_ids_df, problem_evidence_df, raw_posts_df, idea_evaluation_df, run_timestamp=pipeline_run_timestamp
        )
        save_csv(idea_evaluation_df, IDEA_EVALUATION_PATH)
        save_csv(problem_ids_df, PROBLEM_IDS_PATH)
        print(f"  -> Saved to data/idea_evaluation.csv")

    except KeyboardInterrupt:
        print("\n\n[!] Pipeline interrupted by user. Saving data...")
    except Exception as e:
        print(f"\n\n[x] Pipeline error: {e}")
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
            save_csv(idea_evaluation_df, IDEA_EVALUATION_PATH)
        except Exception as save_err:
            print(f"  [x] Error saving CSVs: {save_err}")

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
