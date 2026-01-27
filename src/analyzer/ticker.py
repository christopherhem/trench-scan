import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from src.database.models import Ticker, Mention, TrendSnapshot
from src.scraper.twitter import Tweet

logger = logging.getLogger(__name__)


# Known major coins to filter out (we want new/small caps)
KNOWN_COINS = {
    "BTC", "ETH", "SOL", "USDT", "USDC", "BNB", "XRP", "ADA", "DOGE", "SHIB",
    "DOT", "MATIC", "LTC", "AVAX", "LINK", "UNI", "ATOM", "XLM", "ALGO", "VET",
    "FIL", "THETA", "XMR", "AAVE", "EOS", "MKR", "XTZ", "NEO", "IOTA", "DASH",
    "ZEC", "ENJ", "BAT", "COMP", "SNX", "YFI", "SUSHI", "CRV", "1INCH", "GRT",
    "APE", "PEPE", "WIF", "BONK", "FLOKI", "MEME", "WOJAK", "TURBO", "BOB",
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD",  # Fiat
    "NFT", "NFTS", "DAO", "DEFI", "WEB3", "AI",  # Generic terms
}

# Common false positives
FALSE_POSITIVES = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HAD",
    "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HIS",
    "HOW", "ITS", "LET", "MAY", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO",
    "BOY", "DID", "OWN", "SAY", "SHE", "TOO", "USE", "CEO", "IPO", "USA",
    "UK", "EU", "US", "PT", "EST", "PST", "GMT", "UTC", "AM", "PM",
    "IMO", "TBH", "FYI", "ASAP", "AMA", "ATH", "ATL", "DCA", "FOMO", "FUD",
    "HODL", "WAGMI", "NGMI", "GM", "GN", "LFG", "NFA", "DYOR",
}


@dataclass
class TickerMention:
    """Extracted ticker mention with context"""

    symbol: str
    tweet: Tweet
    confidence: float  # 0-1, how confident we are this is a real ticker


@dataclass
class TrendingTicker:
    """Ticker with trending metrics"""

    symbol: str
    mentions_1h: int
    mentions_24h: int
    velocity: float  # mentions per hour rate of change
    score: float
    first_seen: datetime
    latest_tweet: Optional[Tweet] = None


class TickerAnalyzer:
    """Analyzes tweets to extract and score ticker mentions"""

    # Regex pattern for ticker symbols ($TICKER)
    TICKER_PATTERN = re.compile(r'\$([A-Z]{2,10})\b', re.IGNORECASE)

    # Pattern for contract addresses
    CONTRACT_PATTERNS = {
        "solana": re.compile(r'\b([1-9A-HJ-NP-Za-km-z]{32,44})\b'),
        "ethereum": re.compile(r'\b(0x[a-fA-F0-9]{40})\b'),
    }

    def __init__(self, db: Session):
        self.db = db

    def extract_tickers(self, tweets: list[Tweet]) -> list[TickerMention]:
        """
        Extract ticker symbols from a list of tweets.

        Args:
            tweets: List of Tweet objects to analyze

        Returns:
            List of TickerMention objects
        """
        mentions = []

        for tweet in tweets:
            # Find all $TICKER mentions in tweet text
            matches = self.TICKER_PATTERN.findall(tweet.text)

            for match in matches:
                symbol = match.upper()

                # Skip known coins and false positives
                if symbol in KNOWN_COINS or symbol in FALSE_POSITIVES:
                    continue

                # Skip very short tickers (likely noise)
                if len(symbol) < 3:
                    continue

                # Calculate confidence based on context
                confidence = self._calculate_confidence(symbol, tweet)

                if confidence > 0.3:  # Minimum threshold
                    mentions.append(
                        TickerMention(symbol=symbol, tweet=tweet, confidence=confidence)
                    )

        logger.info(f"Extracted {len(mentions)} ticker mentions from {len(tweets)} tweets")
        return mentions

    def _calculate_confidence(self, symbol: str, tweet: Tweet) -> float:
        """
        Calculate confidence score that this is a real memecoin ticker.

        Factors:
        - Tweet engagement (likes, retweets)
        - Presence of contract address
        - Memecoin-related keywords
        - Author follower count
        """
        score = 0.5  # Base score

        text_lower = tweet.text.lower()

        # Boost for memecoin-related keywords
        memecoin_keywords = [
            "memecoin", "meme coin", "gem", "100x", "1000x", "moon",
            "degen", "ape", "launch", "presale", "stealth", "fair launch",
            "ca:", "contract:", "dexscreener", "birdeye", "pump.fun",
        ]
        keyword_matches = sum(1 for kw in memecoin_keywords if kw in text_lower)
        score += min(keyword_matches * 0.1, 0.3)

        # Boost for engagement
        if tweet.likes > 100:
            score += 0.1
        if tweet.likes > 1000:
            score += 0.1
        if tweet.retweets > 50:
            score += 0.1

        # Boost for contract address presence
        for chain, pattern in self.CONTRACT_PATTERNS.items():
            if pattern.search(tweet.text):
                score += 0.2
                break

        # Cap at 1.0
        return min(score, 1.0)

    def process_mentions(self, mentions: list[TickerMention]) -> dict[str, int]:
        """
        Process ticker mentions and save to database.

        Args:
            mentions: List of TickerMention objects

        Returns:
            Dict of {symbol: mention_count}
        """
        mention_counts = defaultdict(int)

        for mention in mentions:
            # Get or create ticker
            ticker = (
                self.db.query(Ticker)
                .filter(Ticker.symbol == mention.symbol)
                .first()
            )

            if not ticker:
                ticker = Ticker(
                    symbol=mention.symbol,
                    first_seen=mention.tweet.timestamp,
                    total_mentions=0,
                )
                self.db.add(ticker)
                self.db.flush()
                logger.info(f"New ticker discovered: ${mention.symbol}")

            # Check if we already have this tweet
            existing = (
                self.db.query(Mention)
                .filter(Mention.tweet_id == mention.tweet.tweet_id)
                .first()
            )

            if not existing:
                # Add mention
                db_mention = Mention(
                    ticker_id=ticker.id,
                    tweet_id=mention.tweet.tweet_id,
                    tweet_text=mention.tweet.text[:2000],  # Truncate if needed
                    tweet_url=mention.tweet.url,
                    author_username=mention.tweet.author_username,
                    author_followers=mention.tweet.author_followers,
                    likes=mention.tweet.likes,
                    retweets=mention.tweet.retweets,
                    timestamp=mention.tweet.timestamp,
                )
                self.db.add(db_mention)

                # Update ticker stats
                ticker.total_mentions += 1
                ticker.last_seen = datetime.utcnow()

                mention_counts[mention.symbol] += 1

        self.db.commit()
        return dict(mention_counts)

    def calculate_trending(self, limit: int = 20) -> list[TrendingTicker]:
        """
        Calculate trending tickers based on recent mention velocity.

        Args:
            limit: Number of top trending tickers to return

        Returns:
            List of TrendingTicker objects sorted by score
        """
        now = datetime.utcnow()
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(hours=24)

        trending = []

        # Get all tickers with recent activity
        tickers = (
            self.db.query(Ticker)
            .filter(Ticker.last_seen >= day_ago)
            .all()
        )

        for ticker in tickers:
            # Count mentions in different time windows
            mentions_1h = (
                self.db.query(func.count(Mention.id))
                .filter(
                    Mention.ticker_id == ticker.id,
                    Mention.timestamp >= hour_ago,
                )
                .scalar()
            )

            mentions_24h = (
                self.db.query(func.count(Mention.id))
                .filter(
                    Mention.ticker_id == ticker.id,
                    Mention.timestamp >= day_ago,
                )
                .scalar()
            )

            # Calculate velocity (mentions per hour over last 24h vs last hour)
            avg_hourly = mentions_24h / 24 if mentions_24h > 0 else 0
            velocity = (mentions_1h - avg_hourly) / max(avg_hourly, 1)

            # Calculate trending score
            # Weighted: recent mentions matter more + velocity bonus
            score = (mentions_1h * 10) + (mentions_24h * 1) + (velocity * 5)

            # Get latest tweet for this ticker
            latest_mention = (
                self.db.query(Mention)
                .filter(Mention.ticker_id == ticker.id)
                .order_by(Mention.timestamp.desc())
                .first()
            )

            latest_tweet = None
            if latest_mention:
                latest_tweet = Tweet(
                    tweet_id=latest_mention.tweet_id,
                    text=latest_mention.tweet_text,
                    url=latest_mention.tweet_url or "",
                    author_username=latest_mention.author_username,
                    author_followers=latest_mention.author_followers,
                    likes=latest_mention.likes,
                    retweets=latest_mention.retweets,
                    timestamp=latest_mention.timestamp,
                )

            # Save snapshot
            snapshot = TrendSnapshot(
                ticker_id=ticker.id,
                mentions_1h=mentions_1h,
                mentions_24h=mentions_24h,
                velocity=velocity,
                score=score,
            )
            self.db.add(snapshot)

            trending.append(
                TrendingTicker(
                    symbol=ticker.symbol,
                    mentions_1h=mentions_1h,
                    mentions_24h=mentions_24h,
                    velocity=velocity,
                    score=score,
                    first_seen=ticker.first_seen,
                    latest_tweet=latest_tweet,
                )
            )

        self.db.commit()

        # Sort by score and return top results
        trending.sort(key=lambda x: x.score, reverse=True)
        return trending[:limit]

    def get_new_tickers(self, hours: int = 1) -> list[Ticker]:
        """Get tickers first seen in the last N hours"""
        since = datetime.utcnow() - timedelta(hours=hours)
        return (
            self.db.query(Ticker)
            .filter(Ticker.first_seen >= since)
            .order_by(Ticker.first_seen.desc())
            .all()
        )
