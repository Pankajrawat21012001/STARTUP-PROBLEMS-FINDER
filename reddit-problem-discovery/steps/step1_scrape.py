"""
Step 1: Scrape Reddit posts using PullPush.io API (free, no auth needed).

Searches each subreddit × each search phrase, deduplicates against existing posts,
and fetches top 3 comments per post.

Search strategy:
- All (subreddit, phrase) pairs are shuffled for even coverage across subreddits.
- Per-subreddit cap prevents any single sub from dominating the result set.
- Minimum upvote filter drops unvalidated low-signal posts.
- sort=score (descending) maximizes high-quality community-validated results.
- PullPush.io is a free Pushshift replacement — no API key or registration required.
"""

import os
import time
import random
import requests
from datetime import datetime
from urllib.parse import quote_plus


# PullPush.io API base URLs (free, no auth)
PULLPUSH_SUBMISSION_URL = "https://api.pullpush.io/reddit/search/submission/"
PULLPUSH_COMMENT_URL = "https://api.pullpush.io/reddit/search/comment/"

HEADERS = {
    "User-Agent": "ProblemDiscoveryBot/1.0 (startup research project)"
}


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
    target_new_posts = int(os.getenv("TARGET_NEW_POSTS", "100"))
    max_per_sub = int(os.getenv("MAX_POSTS_PER_SUBREDDIT", "3"))
    min_upvotes = int(os.getenv("MIN_UPVOTES", "3"))

    # 1A: Flatten all (subreddit, phrase) combinations and shuffle for even coverage
    search_pairs = [(sub, phrase) for sub in subreddits for phrase in search_phrases]
    random.shuffle(search_pairs)
    total_searches = len(search_pairs)

    print(f"  -> Target new posts to collect: {target_new_posts}")
    print(f"  -> Per-subreddit cap: {max_per_sub} posts max per subreddit")
    print(f"  -> Minimum upvotes required: {min_upvotes}")
    print(f"  -> Maximum search capacity: {len(subreddits)} subreddits x {len(search_phrases)} phrases = {total_searches} searches (shuffled)")
    print(f"  -> Data source: PullPush.io API (free, no API key needed)")

    new_posts = []
    seen_in_this_run = set()
    skipped_existing = 0
    skipped_low_upvotes = 0
    skipped_sub_cap = 0
    search_count = 0
    posts_per_sub = {}  # 1B: Track count per subreddit
    consecutive_errors = 0  # Track consecutive errors for backoff

    for sub_name, phrase in search_pairs:
        if len(new_posts) >= target_new_posts:
            break

        search_count += 1
        print(f"  -> [{search_count}/{total_searches}] Searching r/{sub_name} for '{phrase}'...")

        try:
            # Build PullPush.io API URL
            params = {
                "subreddit": sub_name,
                "q": phrase,
                "sort": "score",
                "sort_type": "desc",
                "size": 100,
            }
            # Add minimum score filter server-side
            if min_upvotes > 0:
                params["score"] = f">{min_upvotes}"

            response = _make_pullpush_request(PULLPUSH_SUBMISSION_URL, params)
            if response is None:
                consecutive_errors += 1
                # Exponential backoff on consecutive errors
                if consecutive_errors >= 3:
                    wait_time = min(30, 5 * consecutive_errors)
                    print(f"     [!] {consecutive_errors} consecutive errors. Backing off for {wait_time}s...")
                    time.sleep(wait_time)
                continue

            consecutive_errors = 0  # Reset on success
            posts_data = response.get("data", [])
            query_new_posts_count = 0

            for post_data in posts_data:
                if len(new_posts) >= target_new_posts:
                    break

                post_id = str(post_data.get("id", ""))

                if not post_id or post_id == "None":
                    continue

                # Deduplication: skip if already in existing data or seen this run
                if post_id in existing_post_ids:
                    skipped_existing += 1
                    continue
                if post_id in seen_in_this_run:
                    continue

                seen_in_this_run.add(post_id)

                # 1C: Minimum upvote filter — drop unvalidated low-signal posts
                post_score = int(post_data.get("score", 0))
                if post_score < min_upvotes:
                    skipped_low_upvotes += 1
                    continue

                # 1B: Per-subreddit diversity cap
                sub_key = post_data.get("subreddit", sub_name)
                sub_count = posts_per_sub.get(sub_key, 0)
                if sub_count >= max_per_sub:
                    skipped_sub_cap += 1
                    continue

                # 1F: Log the new post discovery with upvote count
                title_preview = post_data.get("title", "")
                if len(title_preview) > 60:
                    title_preview = title_preview[:57] + "..."
                print(f'     [+] Found: "{title_preview}" | up:{post_score} upvotes | r/{sub_key} (ID: {post_id})')
                print(f"         Fetching comments for post {post_id}...")

                # Fetch top 3 comments
                top_comments = _get_top_comments(post_id)

                # Build post dict (same format as before — downstream steps unchanged)
                permalink = post_data.get("permalink", "")
                post_dict = {
                    "post_id": post_id,
                    "title": post_data.get("title", ""),
                    "body": post_data.get("selftext", ""),
                    "top_comments": top_comments,
                    "subreddit": post_data.get("subreddit", ""),
                    "upvotes": post_score,
                    "comment_count": int(post_data.get("num_comments", 0)),
                    "post_url": f"https://www.reddit.com{permalink}" if permalink else "",
                    "created_utc": datetime.utcfromtimestamp(post_data.get("created_utc", 0)).isoformat(),
                    "scraped_at": datetime.now().isoformat(),
                    "passed_noise_filter": None
                }
                new_posts.append(post_dict)
                query_new_posts_count += 1
                posts_per_sub[sub_key] = sub_count + 1

            if query_new_posts_count > 0:
                print(f"     -> Added {query_new_posts_count} new posts to processing queue (Total: {len(new_posts)}/{target_new_posts})")

            # Rate limit: 2 seconds between search calls (PullPush.io is generous but be polite)
            time.sleep(2)

        except Exception as e:
            print(f"     [!] Error searching r/{sub_name} for '{phrase}': {e}")
            consecutive_errors += 1
            time.sleep(2)
            continue

    if len(new_posts) >= target_new_posts:
        print(f"\n  -> Target reached ({len(new_posts)}/{target_new_posts}). Stopping scraping.")

    print(f"  -> Found {len(new_posts) + skipped_existing} raw posts matching queries")
    print(f"  -> After deduplication: {len(new_posts)} new posts ({skipped_existing} already seen)")
    print(f"  -> Skipped: {skipped_low_upvotes} low-upvote posts, {skipped_sub_cap} posts over per-sub cap")
    print(f"  -> Subreddits that contributed: {len(posts_per_sub)}")

    return new_posts


def _make_pullpush_request(url, params, max_retries=3):
    """
    Make a request to PullPush.io API with retry logic.

    Args:
        url: API endpoint URL
        params: query parameters dict
        max_retries: number of retry attempts

    Returns:
        parsed JSON response dict, or None on failure
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=30)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                # Rate limited — back off and retry
                wait_time = 10 * (attempt + 1)
                print(f"     [!] Rate limited by PullPush.io. Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                continue
            elif response.status_code == 521:
                # Cloudflare error — server temporarily down
                wait_time = 15 * (attempt + 1)
                print(f"     [!] PullPush.io temporarily down (521). Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                print(f"     [!] PullPush.io returned status {response.status_code}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                return None

        except requests.exceptions.Timeout:
            print(f"     [!] Request timed out (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(5)
            continue
        except Exception as e:
            print(f"     [!] Request error: {e} (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(5)
            continue

    return None


def _get_top_comments(post_id):
    """Fetch top 3 comments for a post using PullPush.io comment search."""
    comments = []
    try:
        # PullPush uses link_id with t3_ prefix to find comments for a specific post
        params = {
            "link_id": f"t3_{post_id}",
            "sort": "score",
            "sort_type": "desc",
            "size": 5,  # Fetch a few extra in case some are deleted
        }

        response = _make_pullpush_request(PULLPUSH_COMMENT_URL, params, max_retries=2)
        if response:
            for comment_data in response.get("data", []):
                if len(comments) >= 3:
                    break
                body = comment_data.get("body", "")
                if body and body not in ("[deleted]", "[removed]"):
                    comments.append(body.replace("\n", " ").strip())

    except Exception:
        pass  # Comments may not be available

    return " || ".join(comments)
