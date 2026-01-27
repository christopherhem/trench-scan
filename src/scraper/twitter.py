import logging
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass
from pathlib import Path

from twscrape import API, gather
from twscrape.logger import set_log_level

logger = logging.getLogger(__name__)

# Suppress twscrape debug logs
set_log_level("WARNING")


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
    """Scraper for Twitter/X using twscrape"""

    def __init__(self, db_path: str = "twscrape_accounts.db"):
        self.db_path = db_path
        self.api = API(db_path)
        self._initialized = False

    async def add_account(self, username: str, password: str, email: str, email_password: str = ""):
        """
        Add a Twitter account for scraping.

        Args:
            username: Twitter username
            password: Twitter password
            email: Email associated with the account
            email_password: Email password (for verification if needed)
        """
        await self.api.pool.add_account(username, password, email, email_password)
        await self.api.pool.login_all()
        logger.info(f"Added Twitter account: @{username}")

    async def check_accounts(self) -> bool:
        """Check if we have any logged-in accounts"""
        accounts = await self.api.pool.accounts_info()
        active = [a for a in accounts if a["active"]]
        if active:
            logger.info(f"Found {len(active)} active Twitter account(s)")
            return True
        else:
            logger.warning("No active Twitter accounts. Add one with 'python main.py add-account'")
            return False

    async def search_tweets(
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
        if not await self.check_accounts():
            return []

        try:
            tweets = []
            async for tweet in self.api.search(query, limit=max_results):
                try:
                    parsed = self._parse_tweet(tweet)
                    if parsed:
                        if since and parsed.timestamp < since:
                            continue
                        tweets.append(parsed)
                except Exception as e:
                    logger.warning(f"Failed to parse tweet: {e}")
                    continue

            logger.info(f"Found {len(tweets)} tweets for query: {query}")
            return tweets

        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            return []

    async def get_user_tweets(
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
        if not await self.check_accounts():
            return []

        try:
            # First get user ID
            user = await self.api.user_by_login(username)
            if not user:
                logger.warning(f"User @{username} not found")
                return []

            tweets = []
            async for tweet in self.api.user_tweets(user.id, limit=max_results):
                try:
                    parsed = self._parse_tweet(tweet)
                    if parsed:
                        if since and parsed.timestamp < since:
                            continue
                        tweets.append(parsed)
                except Exception as e:
                    logger.warning(f"Failed to parse tweet: {e}")
                    continue

            logger.info(f"Found {len(tweets)} tweets from @{username}")
            return tweets

        except Exception as e:
            logger.error(f"Failed to get tweets from @{username}: {e}")
            return []

    def _parse_tweet(self, tweet) -> Optional[Tweet]:
        """Parse twscrape tweet object into our Tweet dataclass"""
        try:
            return Tweet(
                tweet_id=str(tweet.id),
                text=tweet.rawContent,
                url=f"https://twitter.com/{tweet.user.username}/status/{tweet.id}",
                author_username=tweet.user.username,
                author_followers=tweet.user.followersCount or 0,
                likes=tweet.likeCount or 0,
                retweets=tweet.retweetCount or 0,
                timestamp=tweet.date.replace(tzinfo=timezone.utc) if tweet.date.tzinfo is None else tweet.date,
            )
        except Exception as e:
            logger.warning(f"Error parsing tweet: {e}")
            return None

    async def search_memecoin_terms(self, max_results: int = 100) -> list[Tweet]:
        """
        Search for common memecoin-related terms.

        Returns combined results from multiple searches.
        """
        search_terms = [
            "$",  # Catches ticker mentions
            "memecoin",
            "100x gem",
            "solana memecoin",
            "base memecoin",
            "pump.fun",
            "new ca",
        ]

        all_tweets = []
        seen_ids = set()

        per_term = max(10, max_results // len(search_terms))

        for term in search_terms:
            tweets = await self.search_tweets(term, max_results=per_term)
            for tweet in tweets:
                if tweet.tweet_id not in seen_ids:
                    seen_ids.add(tweet.tweet_id)
                    all_tweets.append(tweet)

        return all_tweets
