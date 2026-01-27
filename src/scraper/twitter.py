import re
import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

from ntscraper import Nitter

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
    """Scraper for Twitter/X using Nitter instances"""

    # List of known working Nitter instances (may need updates)
    NITTER_INSTANCES = [
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.woodland.cafe",
        "https://nitter.1d4.us",
    ]

    def __init__(self):
        self.scraper = Nitter()
        self._working_instance = None

    def _find_working_instance(self) -> Optional[str]:
        """Find a working Nitter instance"""
        if self._working_instance:
            return self._working_instance

        for instance in self.NITTER_INSTANCES:
            try:
                # Test the instance
                self.scraper.get_tweets("elonmusk", mode="user", number=1, instance=instance)
                self._working_instance = instance
                logger.info(f"Using Nitter instance: {instance}")
                return instance
            except Exception as e:
                logger.warning(f"Instance {instance} failed: {e}")
                continue

        logger.error("No working Nitter instances found")
        return None

    def search_tweets(
        self,
        query: str,
        max_results: int = 50,
        since: Optional[datetime] = None,
    ) -> list[Tweet]:
        """
        Search for tweets matching a query.

        Args:
            query: Search query (e.g., "$PEPE memecoin")
            max_results: Maximum number of tweets to return
            since: Only return tweets after this time

        Returns:
            List of Tweet objects
        """
        instance = self._find_working_instance()
        if not instance:
            logger.error("Cannot search - no working Nitter instance")
            return []

        try:
            results = self.scraper.get_tweets(
                query, mode="term", number=max_results, instance=instance
            )

            tweets = []
            for tweet_data in results.get("tweets", []):
                try:
                    tweet = self._parse_tweet(tweet_data)
                    if tweet:
                        if since and tweet.timestamp < since:
                            continue
                        tweets.append(tweet)
                except Exception as e:
                    logger.warning(f"Failed to parse tweet: {e}")
                    continue

            logger.info(f"Found {len(tweets)} tweets for query: {query}")
            return tweets

        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            # Reset instance to try another next time
            self._working_instance = None
            return []

    def get_user_tweets(
        self,
        username: str,
        max_results: int = 20,
        since: Optional[datetime] = None,
    ) -> list[Tweet]:
        """
        Get recent tweets from a specific user.

        Args:
            username: Twitter username (without @)
            max_results: Maximum number of tweets to return
            since: Only return tweets after this time

        Returns:
            List of Tweet objects
        """
        instance = self._find_working_instance()
        if not instance:
            logger.error("Cannot get user tweets - no working Nitter instance")
            return []

        try:
            results = self.scraper.get_tweets(
                username, mode="user", number=max_results, instance=instance
            )

            tweets = []
            for tweet_data in results.get("tweets", []):
                try:
                    tweet = self._parse_tweet(tweet_data, default_username=username)
                    if tweet:
                        if since and tweet.timestamp < since:
                            continue
                        tweets.append(tweet)
                except Exception as e:
                    logger.warning(f"Failed to parse tweet: {e}")
                    continue

            logger.info(f"Found {len(tweets)} tweets from @{username}")
            return tweets

        except Exception as e:
            logger.error(f"Failed to get tweets from @{username}: {e}")
            self._working_instance = None
            return []

    def _parse_tweet(self, tweet_data: dict, default_username: str = "unknown") -> Optional[Tweet]:
        """Parse raw tweet data into Tweet object"""
        try:
            # Extract tweet ID from link
            link = tweet_data.get("link", "")
            tweet_id = link.split("/")[-1].split("#")[0] if link else None

            if not tweet_id:
                return None

            # Parse timestamp
            date_str = tweet_data.get("date", "")
            try:
                timestamp = datetime.strptime(date_str, "%b %d, %Y · %I:%M %p UTC")
            except ValueError:
                timestamp = datetime.utcnow()

            # Parse engagement stats
            stats = tweet_data.get("stats", {})
            likes = self._parse_stat(stats.get("likes", "0"))
            retweets = self._parse_stat(stats.get("retweets", "0"))

            # Get username from tweet data or use default
            username = tweet_data.get("user", {}).get("username", default_username)

            return Tweet(
                tweet_id=tweet_id,
                text=tweet_data.get("text", ""),
                url=f"https://twitter.com{link}" if link.startswith("/") else link,
                author_username=username,
                author_followers=0,  # Not always available from Nitter
                likes=likes,
                retweets=retweets,
                timestamp=timestamp,
            )
        except Exception as e:
            logger.warning(f"Error parsing tweet: {e}")
            return None

    def _parse_stat(self, stat: str) -> int:
        """Parse engagement stat (handles K, M suffixes)"""
        if not stat:
            return 0
        stat = str(stat).strip().upper()
        try:
            if "K" in stat:
                return int(float(stat.replace("K", "")) * 1000)
            elif "M" in stat:
                return int(float(stat.replace("M", "")) * 1000000)
            return int(stat.replace(",", ""))
        except ValueError:
            return 0

    def search_memecoin_terms(self, max_results: int = 100) -> list[Tweet]:
        """
        Search for common memecoin-related terms.

        Returns combined results from multiple searches.
        """
        search_terms = [
            "memecoin",
            "100x gem",
            "solana memecoin",
            "base memecoin",
            "degen play",
            "new launch token",
            "presale token",
        ]

        all_tweets = []
        seen_ids = set()

        for term in search_terms:
            tweets = self.search_tweets(term, max_results=max_results // len(search_terms))
            for tweet in tweets:
                if tweet.tweet_id not in seen_ids:
                    seen_ids.add(tweet.tweet_id)
                    all_tweets.append(tweet)

        return all_tweets
