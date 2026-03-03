"""
Community Trip Reports Tool — searches Reddit for recent posts mentioning a trail or route.

Mock-first implementation. Live path requires PRAW installed and Reddit app credentials.

Live API setup (when ready):
  1. pip install praw
  2. Create a Reddit app at https://www.reddit.com/prefs/apps (script type)
  3. Add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET to .env

Data is labeled as community_reports (unverified) throughout the pipeline.
"""

from logger import get_logger
from tools.base import mock_scenario, use_mock

log = get_logger(__name__)

_DAYS_BACK  = 14  # look-back window for "recent" trip reports
_SUBREDDITS = ["Cascades", "PNWhiking", "WTA", "hiking"]


def get_community_reports(trail_name: str, region: str = "") -> dict:
    """Return recent Reddit trip reports mentioning the trail or route."""
    if use_mock():
        return _mock_reports()
    try:
        return _live_reports(trail_name, region)
    except Exception as e:
        log.warning(f"Reddit API failed ({e}) — returning empty community reports")
        return {
            "posts":      [],
            "post_count": 0,
            "days_back":  _DAYS_BACK,
            "source":     "community_reports",
            "notes":      "Community trip report data unavailable.",
            "_error":     str(e),
        }


def _live_reports(trail_name: str, region: str) -> dict:
    """
    Live Reddit query via PRAW.
    Requires: pip install praw
    Requires: REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env
    """
    try:
        import os

        import praw
    except ImportError:
        raise RuntimeError("PRAW not installed. Run: pip install praw")

    client_id     = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set in .env")

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent="TrailOps/1.0 (trail conditions research — read-only)",
    )

    query         = f"{trail_name} {region}".strip()
    subreddit_str = "+".join(_SUBREDDITS)
    results       = reddit.subreddit(subreddit_str).search(
        query, sort="new", time_filter="month", limit=15
    )

    from datetime import datetime, timezone
    cutoff = datetime.now(timezone.utc).timestamp() - (_DAYS_BACK * 86400)
    posts  = []
    for post in results:
        if post.created_utc < cutoff:
            continue
        date_str = datetime.fromtimestamp(post.created_utc, tz=timezone.utc).strftime("%Y-%m-%d")
        snippet  = (post.selftext or post.title)[:400].replace("\n", " ").strip()
        posts.append({
            "subreddit": f"r/{post.subreddit.display_name}",
            "title":     post.title,
            "date":      date_str,
            "snippet":   snippet,
            "url":       f"https://reddit.com{post.permalink}",
        })

    return {
        "posts":      posts,
        "post_count": len(posts),
        "days_back":  _DAYS_BACK,
        "source":     "community_reports",
        "notes":      _build_notes(posts),
    }


def _build_notes(posts: list) -> str:
    if not posts:
        return f"No community trip reports found in the last {_DAYS_BACK} days."
    n = len(posts)
    return (
        f"{n} community trip report{'s' if n != 1 else ''} found in the last {_DAYS_BACK} days. "
        "Unverified — check each source for details."
    )


def _mock_reports() -> dict:
    scenario = mock_scenario()

    if scenario == 1:
        # Goat Rocks — clear conditions, positive reports
        posts = [
            {
                "subreddit": "r/Cascades",
                "title":     "Goat Rocks — Snowgrass Flat TR (7/19)",
                "date":      "2024-07-19",
                "snippet": (
                    "Did the Snowgrass Flat loop over the weekend. Trail is in excellent shape — "
                    "no snow, wildflowers are at absolute peak right now. The Cispus River ford was "
                    "knee-deep but manageable. Camp at Snowgrass Flat was packed Saturday, quiet Sunday. "
                    "Highly recommend if you can snag a permit."
                ),
                "url": "https://www.reddit.com/r/Cascades/comments/mock_goatrocks_loop",
            },
            {
                "subreddit": "r/PNWhiking",
                "title":     "Goat Rocks Wilderness — Hawkeye Point scramble + Snowgrass",
                "date":      "2024-07-17",
                "snippet": (
                    "Three-day trip in Goat Rocks this week. Snow is gone from the PCT corridor. "
                    "Hawkeye scramble was exposed but dry. Water flowing at all listed sources. "
                    "Bear box at Snowgrass Flat is a good idea — we saw fresh diggings near camp. "
                    "Overall a great trip, conditions about as good as it gets up there."
                ),
                "url": "https://www.reddit.com/r/PNWhiking/comments/mock_hawkeye_pt",
            },
        ]

    elif scenario == 2:
        # Enchantments — smoke and poor visibility reports
        posts = [
            {
                "subreddit": "r/Cascades",
                "title":     "Enchantments Traverse TR — smoke advisory (7/22)",
                "date":      "2024-07-22",
                "snippet": (
                    "Just got back from the Enchantments. Core Zone was incredible terrain but we had "
                    "significant smoke from Oregon fires by day two. Visibility dropped to maybe 2 miles. "
                    "Eyes burning by afternoon. AQI was hitting 160+ at elevation. If you're sensitive "
                    "to air quality, consider postponing."
                ),
                "url": "https://www.reddit.com/r/Cascades/comments/mock_enchantments_smoke",
            },
            {
                "subreddit": "r/WTA",
                "title":     "Enchantments permit trip — smoke cut our stay short",
                "date":      "2024-07-21",
                "snippet": (
                    "Had a 3-day permit but came out after day 2 due to smoke. Snow Bridge Camp was "
                    "awesome until haze rolled in around noon on day 2. The route itself is in great "
                    "shape — snow-free, Leprechaun Lake was stunning. Just check the AQI before you go. "
                    "We had no issues with the route, purely the air quality."
                ),
                "url": "https://www.reddit.com/r/WTA/comments/mock_enchantments_permit",
            },
        ]

    else:
        # Olympic High Divide — high water, mud, flash flood watch
        posts = [
            {
                "subreddit": "r/PNWhiking",
                "title":     "Olympic High Divide — Hoh River crossing report (7/20)",
                "date":      "2024-07-20",
                "snippet": (
                    "Did the High Divide loop this week. Hoh River crossing near Glacier Meadows was "
                    "thigh-deep and fast-moving — one in our group almost lost footing. Strongly recommend "
                    "trekking poles and unbuckle your hip belt before crossing. The High Divide ridge "
                    "itself was gorgeous but approach trails are very muddy throughout."
                ),
                "url": "https://www.reddit.com/r/PNWhiking/comments/mock_highd_water",
            },
            {
                "subreddit": "r/Cascades",
                "title":     "High Divide + Seven Lakes Basin — wet conditions this week",
                "date":      "2024-07-18",
                "snippet": (
                    "Beautiful but very wet out there right now. Sol Duc Falls trail is muddy from "
                    "trailhead to the basin. Seven Lakes Basin campsites are solid but the final crossing "
                    "before Hoh Lake had us wading mid-thigh. Flash flood watch was in effect our last "
                    "night — we moved camp to higher ground as a precaution."
                ),
                "url": "https://www.reddit.com/r/Cascades/comments/mock_highd_wet",
            },
        ]

    return {
        "posts":      posts,
        "post_count": len(posts),
        "days_back":  _DAYS_BACK,
        "source":     "community_reports",
        "notes":      _build_notes(posts),
        "_mock":      True,
    }
