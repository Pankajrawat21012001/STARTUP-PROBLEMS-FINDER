"""
Step 1: Scrape Reddit posts using ScraperAPI.

Searches each subreddit × each search phrase, deduplicates against existing posts,
and fetches top 3 comments per post.

Search strategy:
- All (subreddit, phrase) pairs are shuffled for even coverage across subreddits.
- Per-subreddit cap prevents any single sub from dominating the result set.
- Minimum upvote filter drops unvalidated low-signal posts.
- sort=top&t=year&limit=100 maximizes high-quality community-validated results.
"""

import os
import time
import random
import requests
from datetime import datetime
from urllib.parse import quote_plus, quote


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
    scraper_api_key = os.getenv("SCRAPER_API_KEY")
    if not scraper_api_key or scraper_api_key == "your_scraperapi_key":
        print("  [!] Warning: SCRAPER_API_KEY is not set in .env. Search calls may fail.")

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

    new_posts = []
    seen_in_this_run = set()
    skipped_existing = 0
    skipped_low_upvotes = 0
    skipped_sub_cap = 0
    search_count = 0
    posts_per_sub = {}  # 1B: Track count per subreddit

    for sub_name, phrase in search_pairs:
        if len(new_posts) >= target_new_posts:
            break

        search_count += 1
        print(f"  -> [{search_count}/{total_searches}] Searching r/{sub_name} for '{phrase}'...")

        try:
            # 1D: URL-encode the phrase separately before building the Reddit URL
            encoded_phrase = quote(phrase, safe='')
            # 1E: sort=top&t=year&limit=100 for maximum high-signal community-validated results
            reddit_url = f"https://www.reddit.com/r/{sub_name}/search.json?q={encoded_phrase}&sort=top&t=year&limit=100&restrict_sr=1"
            scraper_url = f"http://api.scraperapi.com?api_key={scraper_api_key}&url={quote_plus(reddit_url)}"

            response = requests.get(scraper_url, timeout=20)
            if response.status_code != 200:
                print(f"     [!] Error searching r/{sub_name} for '{phrase}' via ScraperAPI (Status: {response.status_code})")
                time.sleep(1)
                continue

            children = response.json().get("data", {}).get("children", [])
            query_new_posts_count = 0

            for child in children:
                if len(new_posts) >= target_new_posts:
                    break

                post_data = child.get("data", {})
                post_id = str(post_data.get("id"))

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
                print(f'     [+] Found: "{title_preview}" | ⬆{post_score} upvotes | r/{sub_key} (ID: {post_id})')
                print(f"         Fetching comments for post {post_id}...")

                # Fetch top 3 comments
                top_comments = _get_top_comments(post_id, scraper_api_key)

                # Build post dict
                post_dict = {
                    "post_id": post_id,
                    "title": post_data.get("title", ""),
                    "body": post_data.get("selftext", ""),
                    "top_comments": top_comments,
                    "subreddit": post_data.get("subreddit", ""),
                    "upvotes": post_score,
                    "comment_count": int(post_data.get("num_comments", 0)),
                    "post_url": f"https://www.reddit.com{post_data.get('permalink', '')}",
                    "created_utc": datetime.utcfromtimestamp(post_data.get("created_utc", 0)).isoformat(),
                    "scraped_at": datetime.now().isoformat(),
                    "passed_noise_filter": None
                }
                new_posts.append(post_dict)
                query_new_posts_count += 1
                posts_per_sub[sub_key] = sub_count + 1

            if query_new_posts_count > 0:
                print(f"     -> Added {query_new_posts_count} new posts to processing queue (Total: {len(new_posts)}/{target_new_posts})")

            # Rate limit: 1 second between search calls
            time.sleep(1)

        except Exception as e:
            print(f"     [!] Error searching r/{sub_name} for '{phrase}': {e}")
            time.sleep(1)
            continue

    if len(new_posts) >= target_new_posts:
        print(f"\n  -> Target reached ({len(new_posts)}/{target_new_posts}). Stopping scraper.")

    print(f"  -> Found {len(new_posts) + skipped_existing} raw posts matching queries")
    print(f"  -> After deduplication: {len(new_posts)} new posts ({skipped_existing} already seen)")
    print(f"  -> Skipped: {skipped_low_upvotes} low-upvote posts, {skipped_sub_cap} posts over per-sub cap")
    print(f"  -> Subreddits that contributed: {len(posts_per_sub)}")

    return new_posts


def _get_top_comments(post_id, scraper_api_key):
    """Fetch top N comments from a post, skipping deleted/removed."""
    comments = []
    try:
        # Construct comments URL through ScraperAPI proxy
        reddit_url = f"https://www.reddit.com/comments/{post_id}.json?limit=3"
        scraper_url = f"http://api.scraperapi.com?api_key={scraper_api_key}&url={quote_plus(reddit_url)}"

        response = requests.get(scraper_url, timeout=15)
        if response.status_code == 200:
            resp_json = response.json()
            # Reddit comments JSON is list of two elements: [post_listing, comments_listing]
            if isinstance(resp_json, list) and len(resp_json) > 1:
                children = resp_json[1].get("data", {}).get("children", [])
                for child in children:
                    if len(comments) >= 3:
                        break
                    comment_data = child.get("data", {})
                    body = comment_data.get("body", "")
                    if body and body not in ("[deleted]", "[removed]"):
                        comments.append(body.replace("\n", " ").strip())
    except Exception:
        pass  # Comments may not be available

    return " || ".join(comments)
