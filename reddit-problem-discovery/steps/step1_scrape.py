"""
Step 1: Scrape Reddit posts using PRAW.

Searches each subreddit × each search phrase, deduplicates against existing posts,
and fetches top 3 comments per post.
"""

import os
import json
import time
from datetime import datetime

import praw


def scrape_reddit(subreddits, search_phrases, existing_post_ids):
    """
    Scrape Reddit for posts matching search phrases.

    Args:
        subreddits: list of subreddit names
        search_phrases: list of search query strings
        existing_post_ids: set of post_id strings already scraped (for dedup)

    Returns:
        list of dicts, each representing a raw post
    """
    # Connect to Reddit
    reddit = praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT"),
        read_only=True
    )

    total_searches = len(subreddits) * len(search_phrases)
    print(f"  → Searching {len(subreddits)} subreddits × {len(search_phrases)} phrases = {total_searches} searches")

    new_posts = []
    seen_in_this_run = set()
    skipped_existing = 0
    search_count = 0

    for sub_name in subreddits:
        try:
            subreddit = reddit.subreddit(sub_name)
            for phrase in search_phrases:
                search_count += 1
                if search_count % 20 == 0:
                    print(f"  → Progress: {search_count}/{total_searches} searches completed...")

                try:
                    results = subreddit.search(
                        phrase,
                        limit=25,
                        sort="relevance",
                        time_filter="month"
                    )

                    for post in results:
                        post_id = str(post.id)

                        # Deduplication: skip if already in existing data or seen this run
                        if post_id in existing_post_ids:
                            skipped_existing += 1
                            continue
                        if post_id in seen_in_this_run:
                            continue

                        seen_in_this_run.add(post_id)

                        # Fetch top 3 comments
                        top_comments = _get_top_comments(post, max_comments=3)

                        # Build post dict
                        post_dict = {
                            "post_id": post_id,
                            "title": str(post.title or ""),
                            "body": str(post.selftext or ""),
                            "top_comments": top_comments,
                            "subreddit": str(post.subreddit.display_name),
                            "upvotes": int(post.score),
                            "comment_count": int(post.num_comments),
                            "post_url": f"https://www.reddit.com{post.permalink}",
                            "created_utc": datetime.utcfromtimestamp(post.created_utc).isoformat(),
                            "scraped_at": datetime.now().isoformat(),
                            "passed_noise_filter": None  # Set in step 2
                        }
                        new_posts.append(post_dict)

                    # Rate limit: 1 second between API calls
                    time.sleep(1)

                except Exception as e:
                    print(f"  ⚠ Error searching r/{sub_name} for '{phrase}': {e}")
                    time.sleep(1)
                    continue

        except Exception as e:
            print(f"  ⚠ Error accessing r/{sub_name}: {e}")
            continue

    print(f"  → Found {len(new_posts) + skipped_existing} raw posts")
    print(f"  → After deduplication: {len(new_posts)} new posts ({skipped_existing} already seen)")

    return new_posts


def _get_top_comments(post, max_comments=3):
    """Fetch top N comments from a post, skipping deleted/removed."""
    comments = []
    try:
        post.comments.replace_more(limit=0)
        for comment in post.comments[:max_comments * 2]:  # fetch extra in case some are deleted
            if len(comments) >= max_comments:
                break
            body = str(comment.body or "")
            if body and body not in ("[deleted]", "[removed]"):
                comments.append(body.replace("\n", " ").strip())
    except Exception:
        pass  # Comments may not be available

    return " || ".join(comments)
