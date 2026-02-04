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


@dataclass
class ContractMention:
    """Extracted contract address mention"""

    address: str
    chain: str
    tweet: Tweet
    is_pump_fun: bool


class TickerAnalyzer:
    """Analyzes tweets to extract and score ticker/contract mentions"""

    # Regex pattern for ticker symbols ($TICKER)
    TICKER_PATTERN = re.compile(r'\$([A-Z]{2,10})\b', re.IGNORECASE)

    # Pattern for contract addresses
    CONTRACT_PATTERNS = {
        "solana": re.compile(r'\b([1-9A-HJ-NP-Za-km-z]{32,44})\b'),
        "ethereum": re.compile(r'\b(0x[a-fA-F0-9]{40})\b'),
    }

    # Pattern specifically for pump.fun addresses (end with "pump")
    PUMP_FUN_PATTERN = re.compile(r'\b([1-9A-HJ-NP-Za-km-z]{32,44}pump)\b')

    def __init__(self, db: Session):
        self.db = db

    def extract_pump_fun_addresses(self, tweets: list[Tweet]) -> list[ContractMention]:
        """
        Extract pump.fun contract addresses from tweets.

        Args:
            tweets: List of Tweet objects to analyze

        Returns:
            List of ContractMention objects for pump.fun addresses
        """
        mentions = []

        for tweet in tweets:
            # Find pump.fun addresses (ending in "pump")
            pump_matches = self.PUMP_FUN_PATTERN.findall(tweet.text)

            for address in pump_matches:
                mentions.append(
                    ContractMention(
                        address=address,
                        chain="solana",
                        tweet=tweet,
                        is_pump_fun=True,
                    )
                )

            # Also check for general Solana addresses mentioned with pump.fun context
            if "pump.fun" in tweet.text.lower() or "pumpfun" in tweet.text.lower():
                sol_matches = self.CONTRACT_PATTERNS["solana"].findall(tweet.text)
                for address in sol_matches:
                    # Skip if already found as pump.fun address
                    if address not in [m.address for m in mentions]:
                        mentions.append(
                            ContractMention(
                                address=address,
                                chain="solana",
                                tweet=tweet,
                                is_pump_fun=True,
                            )
                        )

        logger.info(f"Extracted {len(mentions)} pump.fun addresses from {len(tweets)} tweets")
        return mentions

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
        seen_tweet_ids = set()  # Track tweets processed in this batch

        for mention in mentions:
            # Skip if we already processed this tweet in this batch
            if mention.tweet.tweet_id in seen_tweet_ids:
                continue

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

            # Check if we already have this tweet in database
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

                # Mark tweet as seen in this batch
                seen_tweet_ids.add(mention.tweet.tweet_id)

                # Update ticker stats
                ticker.total_mentions += 1
                ticker.last_seen = datetime.utcnow()

                mention_counts[mention.symbol] += 1

        self.db.commit()
        return dict(mention_counts)

    def process_contracts(self, contracts: list[ContractMention]) -> dict[str, int]:
        """
        Process pump.fun contract mentions and save to database.

        Args:
            contracts: List of ContractMention objects

        Returns:
            Dict of {address: mention_count}
        """
        mention_counts = defaultdict(int)
        seen_tweet_ids = set()

        for contract in contracts:
            if contract.tweet.tweet_id in seen_tweet_ids:
                continue

            # Use shortened address as symbol for display (first 4 + last 4 chars)
            short_addr = f"{contract.address[:4]}...{contract.address[-4:]}"

            # Get or create ticker entry for this contract
            ticker = (
                self.db.query(Ticker)
                .filter(Ticker.contract_address == contract.address)
                .first()
            )

            if not ticker:
                ticker = Ticker(
                    symbol=short_addr,
                    contract_address=contract.address,
                    chain=contract.chain,
                    first_seen=contract.tweet.timestamp,
                    total_mentions=0,
                )
                self.db.add(ticker)
                self.db.flush()
                logger.info(f"New pump.fun token: {contract.address}")

            # Check if tweet already exists
            existing = (
                self.db.query(Mention)
                .filter(Mention.tweet_id == contract.tweet.tweet_id)
                .first()
            )

            if not existing:
                db_mention = Mention(
                    ticker_id=ticker.id,
                    tweet_id=contract.tweet.tweet_id,
                    tweet_text=contract.tweet.text[:2000],
                    tweet_url=contract.tweet.url,
                    author_username=contract.tweet.author_username,
                    author_followers=contract.tweet.author_followers,
                    likes=contract.tweet.likes,
                    retweets=contract.tweet.retweets,
                    timestamp=contract.tweet.timestamp,
                )
                self.db.add(db_mention)
                seen_tweet_ids.add(contract.tweet.tweet_id)

                ticker.total_mentions += 1
                ticker.last_seen = datetime.utcnow()

                mention_counts[contract.address] += 1

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
