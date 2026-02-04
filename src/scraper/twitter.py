import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Tweet:
    """Represents a scraped tweet"""

    tweet_id: str
    text: str
    url: str
    author_username: str
    author_followers: int
    likes: int
    retweets: int
    timestamp: datetime


class TwitterScraper:
    """Scraper for Twitter/X using RapidAPI (twitterapi.io)"""

    BASE_URL = "https://twitterapi-cheap.p.rapidapi.com"

    def __init__(self):
        self.api_key = settings.rapidapi_key
        self.api_host = settings.rapidapi_host

        if not self.api_key:
            logger.warning("RapidAPI key not configured. Set RAPIDAPI_KEY in .env")

    def _get_headers(self) -> dict:
        """Get headers for RapidAPI requests"""
        return {
            "Content-Type": "application/json",
            "x-rapidapi-host": self.api_host,
            "x-rapidapi-key": self.api_key,
        }

    def _get_time_range(self) -> tuple[str, str]:
        """Get time range for the last 24 hours"""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        start_str = start.strftime("%Y-%m-%d_%H:%M:%S_UTC")
        end_str = now.strftime("%Y-%m-%d_%H:%M:%S_UTC")

        return start_str, end_str

    async def search_cashtags(self, cashtags: list[str], max_items: int = 20) -> list[Tweet]:
        """
        Search for tweets mentioning specific cashtags.

        Args:
            cashtags: List of cashtags to search (without $)
            max_items: Maximum tweets to return per cashtag

        Returns:
            List of Tweet objects
        """
        if not self.api_key:
            logger.error("RapidAPI key not configured")
            return []

        start_time, end_time = self._get_time_range()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/twitter/cashtags",
                    headers=self._get_headers(),
                    json={
                        "cashtags": cashtags,
                        "startTime": start_time,
                        "endTime": end_time,
                        "sortBy": "Latest",
                        "maxItems": max_items,
                    },
                )

                if response.status_code != 200:
                    logger.error(f"API error: {response.status_code} - {response.text[:200]}")
                    return []

                data = response.json()
                logger.debug(f"API response: {data}")
                tweets = self._parse_cashtag_response(data)
                logger.info(f"Found {len(tweets)} tweets for cashtags: {cashtags}")
                return tweets

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def search_keyword(self, keyword: str, max_items: int = 20) -> list[Tweet]:
        """
        Search for tweets matching a keyword.

        Args:
            keyword: Search keyword
            max_items: Maximum tweets to return

        Returns:
            List of Tweet objects
        """
        if not self.api_key:
            logger.error("RapidAPI key not configured")
            return []

        start_time, end_time = self._get_time_range()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/twitter/search",
                    headers=self._get_headers(),
                    json={
                        "query": keyword,
                        "startTime": start_time,
                        "endTime": end_time,
                        "sortBy": "Latest",
                        "maxItems": max_items,
                    },
                )

                if response.status_code != 200:
                    logger.error(f"API error: {response.status_code} - {response.text[:200]}")
                    return []

                data = response.json()
                tweets = self._parse_search_response(data)
                logger.info(f"Found {len(tweets)} tweets for keyword: {keyword}")
                return tweets

        except Exception as e:
            logger.error(f"Search failed for '{keyword}': {e}")
            return []

    def _parse_cashtag_response(self, data) -> list[Tweet]:
        """Parse cashtag API response"""
        tweets = []

        # Log the response structure for debugging
        logger.info(f"API response type: {type(data)}, keys: {data.keys() if isinstance(data, dict) else 'N/A'}")

        # Handle different response structures
        if isinstance(data, list):
            results = data
        elif isinstance(data, dict):
            # Try various possible keys
            results = (
                data.get("results") or
                data.get("tweets") or
                data.get("data") or
                data.get("statuses") or
                []
            )

            # If results is still a dict (keyed by cashtag), flatten it
            if isinstance(results, dict):
                flattened = []
                for key, value in results.items():
                    if isinstance(value, list):
                        flattened.extend(value)
                    elif isinstance(value, dict) and "tweets" in value:
                        flattened.extend(value["tweets"])
                results = flattened
        else:
            results = []

        logger.info(f"Parsing {len(results) if isinstance(results, list) else 0} results")

        if isinstance(results, list):
            for tweet_data in results:
                tweet = self._parse_tweet(tweet_data)
                if tweet:
                    tweets.append(tweet)

        return tweets

    def _parse_search_response(self, data: dict) -> list[Tweet]:
        """Parse search API response"""
        tweets = []

        results = data if isinstance(data, list) else data.get("results", data.get("tweets", []))

        if isinstance(results, list):
            for tweet_data in results:
                tweet = self._parse_tweet(tweet_data)
                if tweet:
                    tweets.append(tweet)

        return tweets

    def _parse_tweet(self, tweet_data: dict) -> Optional[Tweet]:
        """Parse individual tweet from API response"""
        try:
            # Handle various field names from API
            tweet_id = str(tweet_data.get("id") or tweet_data.get("tweet_id") or tweet_data.get("id_str", ""))

            if not tweet_id:
                return None

            text = tweet_data.get("text") or tweet_data.get("full_text") or tweet_data.get("content", "")

            # Get author info
            user = tweet_data.get("user") or tweet_data.get("author") or {}
            username = user.get("username") or user.get("screen_name") or tweet_data.get("username", "unknown")
            followers = user.get("followers_count") or user.get("followersCount", 0)

            # Get engagement
            likes = tweet_data.get("favorite_count") or tweet_data.get("likeCount") or tweet_data.get("likes", 0)
            retweets = tweet_data.get("retweet_count") or tweet_data.get("retweetCount") or tweet_data.get("retweets", 0)

            # Parse timestamp
            created_at = tweet_data.get("created_at") or tweet_data.get("timestamp") or tweet_data.get("date")
            if isinstance(created_at, str):
                try:
                    # Try ISO format
                    timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        # Try Twitter format
                        timestamp = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
                    except ValueError:
                        timestamp = datetime.now(timezone.utc)
            elif isinstance(created_at, (int, float)):
                timestamp = datetime.fromtimestamp(created_at, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            return Tweet(
                tweet_id=tweet_id,
                text=text,
                url=f"https://twitter.com/{username}/status/{tweet_id}",
                author_username=username,
                author_followers=followers or 0,
                likes=likes or 0,
                retweets=retweets or 0,
                timestamp=timestamp,
            )
        except Exception as e:
            logger.warning(f"Error parsing tweet: {e}")
            return None

    async def search_memecoin_terms(self, max_results: int = 100) -> list[Tweet]:
        """
        Search for pump.fun related tweets to find new memecoin launches.

        Returns combined results from multiple searches.
        """
        all_tweets = []
        seen_ids = set()

        # Search for pump.fun related cashtags
        # These are common terms used when sharing new pump.fun launches
        cashtags = [
            "SOL",
            "SOLANA",
            "PUMP",
            "PUMPFUN",
            "MEMECOIN",
            "DEGEN",
            "APE",
            "GEM",
        ]

        cashtag_tweets = await self.search_cashtags(cashtags, max_items=max_results)
        for tweet in cashtag_tweets:
            if tweet.tweet_id not in seen_ids:
                seen_ids.add(tweet.tweet_id)
                all_tweets.append(tweet)

        logger.info(f"Total tweets collected: {len(all_tweets)}")
        return all_tweets
