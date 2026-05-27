"""
Step 2: Noise filter.

Removes low-quality posts based on upvotes, blocked keywords,
physical product indicators, and free-only signals.
Posts that fail are still saved to raw_posts.csv for audit purposes.
"""

import json
import os


def filter_noise(posts, blocklist_path="config/noise_blocklist.json"):
    """
    Filter posts using noise rules.

    Args:
        posts: list of post dicts from step 1
        blocklist_path: path to noise_blocklist.json

    Returns:
        list of post dicts that passed the noise filter
    """
    # Load blocklist config
    with open(blocklist_path, "r", encoding="utf-8") as f:
        blocklist = json.load(f)

    min_upvotes = blocklist.get("min_upvotes", 5)
    blocked_keywords = [kw.lower() for kw in blocklist.get("blocked_keywords", [])]
    physical_keywords = [kw.lower() for kw in blocklist.get("physical_product_keywords", [])]
    free_only_keywords = [kw.lower() for kw in blocklist.get("free_only_keywords", [])]

    passed = []
    removed_reasons = {
        "low_upvotes": 0,
        "blocked_keywords": 0,
        "physical_product": 0,
        "free_only": 0,
        "too_short": 0,
        "link_post": 0
    }

    for post in posts:
        title = str(post.get("title", "")).lower()
        body = str(post.get("body", "")).lower()
        combined = title + " " + body
        upvotes = int(post.get("upvotes", 0))
        failed = False
        reason = None

        # Rule 1: Minimum upvotes
        if upvotes < min_upvotes:
            failed = True
            reason = "low_upvotes"

        # Rule 2: Blocked keywords
        if not failed:
            for kw in blocked_keywords:
                if kw in combined:
                    failed = True
                    reason = "blocked_keywords"
                    break

        # Rule 3: Physical product keywords
        if not failed:
            for kw in physical_keywords:
                if kw in combined:
                    failed = True
                    reason = "physical_product"
                    break

        # Rule 4: Free-only keywords
        if not failed:
            for kw in free_only_keywords:
                if kw in combined:
                    failed = True
                    reason = "free_only"
                    break

        # Rule 5: Empty body + short title (likely link post)
        if not failed:
            if (not body.strip() or body.strip() == "") and len(title) < 20:
                failed = True
                reason = "link_post"

        # Rule 6: Combined text too short
        if not failed:
            if len(combined.strip()) < 50:
                failed = True
                reason = "too_short"

        if failed:
            post["passed_noise_filter"] = False
            removed_reasons[reason] += 1
        else:
            post["passed_noise_filter"] = True
            passed.append(post)

    total_removed = sum(removed_reasons.values())
    print(f"  -> {len(posts)} posts checked")
    print(f"  -> {len(passed)} posts passed noise filter")
    print(f"  -> {total_removed} posts removed (low upvotes: {removed_reasons['low_upvotes']}, "
          f"blocked keywords: {removed_reasons['blocked_keywords']}, "
          f"physical product: {removed_reasons['physical_product']}, "
          f"other: {removed_reasons['free_only'] + removed_reasons['too_short'] + removed_reasons['link_post']})")

    return passed
