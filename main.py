#!/usr/bin/env python3
"""
Trench Scan - Viral Trend Scraper for Memecoin Detection

Usage:
    python main.py scrape     - Run a single scrape cycle
    python main.py dashboard  - Start the web dashboard
    python main.py bot        - Start the Telegram bot
    python main.py run        - Run scraper + dashboard + bot
    python main.py init       - Initialize the database
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import settings
from src.database.models import init_db, SessionLocal, Ticker, Mention
from src.scraper.twitter import TwitterScraper
from src.scraper.pumpfun import PumpFunScraper, PumpFunToken
from src.analyzer.ticker import TickerAnalyzer
from src.dashboard.app import app
from src.bots.telegram_bot import TelegramBot

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("trench_scan.log"),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class ViralToken:
    """Token with combined pump.fun + Twitter data"""
    address: str
    name: str
    symbol: str
    created_timestamp: datetime
    age_minutes: int
    market_cap: float
    twitter_mentions: int
    twitter_engagement: int  # likes + RTs
    viral_score: float
    pump_fun_data: Optional[PumpFunToken] = None


async def run_scrape_cycle():
    """Run a single scrape and analysis cycle"""
    logger.info("Starting scrape cycle...")

    pumpfun = PumpFunScraper()
    twitter = TwitterScraper()

    if not settings.rapidapi_key:
        logger.warning("RapidAPI key not configured - Twitter search disabled")

    db = SessionLocal()

    try:
        # Step 1: Get new tokens from pump.fun (last 6 hours)
        logger.info("Fetching new pump.fun launches...")
        new_tokens = await pumpfun.get_new_tokens(limit=100, max_age_hours=6)
        logger.info(f"Found {len(new_tokens)} new tokens on pump.fun")

        if not new_tokens:
            logger.warning("No new pump.fun tokens found")
            # Fall back to Twitter-only mode
            await run_twitter_only_cycle(twitter, db)
            return

        # Step 2: Search Twitter for mentions of these tokens
        viral_tokens = []
        now = datetime.now(timezone.utc)

        for token in new_tokens:
            # Calculate age in minutes
            age_minutes = int((now - token.created_timestamp).total_seconds() / 60)

            # Store token in database
            db_ticker = db.query(Ticker).filter(Ticker.contract_address == token.address).first()

            if not db_ticker:
                db_ticker = Ticker(
                    symbol=token.symbol,
                    contract_address=token.address,
                    chain="solana",
                    first_seen=token.created_timestamp,
                    total_mentions=0,
                )
                db.add(db_ticker)
                db.flush()
                logger.info(f"New token: ${token.symbol} ({token.address[:8]}...{token.address[-4:]}) - {age_minutes}m old")

            # Search Twitter for this token's CA (if we have API key)
            twitter_mentions = 0
            twitter_engagement = 0

            if settings.rapidapi_key and token.address:
                # Search for the CA on Twitter
                tweets = await twitter.search_cashtags([token.symbol], max_items=10)

                for tweet in tweets:
                    # Check if tweet mentions this specific CA
                    if token.address in tweet.text or token.symbol.upper() in tweet.text.upper():
                        twitter_mentions += 1
                        twitter_engagement += tweet.likes + tweet.retweets

                        # Store mention
                        existing = db.query(Mention).filter(Mention.tweet_id == tweet.tweet_id).first()
                        if not existing:
                            db_mention = Mention(
                                ticker_id=db_ticker.id,
                                tweet_id=tweet.tweet_id,
                                tweet_text=tweet.text[:2000],
                                tweet_url=tweet.url,
                                author_username=tweet.author_username,
                                author_followers=tweet.author_followers,
                                likes=tweet.likes,
                                retweets=tweet.retweets,
                                timestamp=tweet.timestamp,
                            )
                            db.add(db_mention)
                            db_ticker.total_mentions += 1

            # Calculate viral score
            # Factors: age (newer = better), mentions, engagement, market cap
            age_factor = max(0, 1 - (age_minutes / 360))  # 0-1, newer is higher
            mention_factor = min(twitter_mentions * 10, 100)  # Up to 100 points
            engagement_factor = min(twitter_engagement / 10, 50)  # Up to 50 points
            mcap_factor = min(token.market_cap / 10000, 50) if token.market_cap > 0 else 0  # Up to 50 points

            viral_score = (age_factor * 50) + mention_factor + engagement_factor + mcap_factor

            viral_tokens.append(ViralToken(
                address=token.address,
                name=token.name,
                symbol=token.symbol,
                created_timestamp=token.created_timestamp,
                age_minutes=age_minutes,
                market_cap=token.market_cap,
                twitter_mentions=twitter_mentions,
                twitter_engagement=twitter_engagement,
                viral_score=viral_score,
                pump_fun_data=token,
            ))

        db.commit()

        # Sort by viral score
        viral_tokens.sort(key=lambda x: x.viral_score, reverse=True)

        # Log top tokens
        logger.info("=" * 50)
        logger.info("TOP VIRAL PUMP.FUN TOKENS:")
        logger.info("=" * 50)

        for i, token in enumerate(viral_tokens[:10], 1):
            mcap_str = f"${token.market_cap:,.0f}" if token.market_cap > 0 else "N/A"
            logger.info(
                f"{i}. ${token.symbol} | Age: {token.age_minutes}m | "
                f"MCap: {mcap_str} | Tweets: {token.twitter_mentions} | "
                f"Score: {token.viral_score:.0f}"
            )
            logger.info(f"   CA: {token.address}")

        logger.info("=" * 50)
        logger.info("Scrape cycle completed")

    except Exception as e:
        logger.error(f"Scrape cycle failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await pumpfun.close()
        db.close()


async def run_twitter_only_cycle(twitter: TwitterScraper, db):
    """Fallback: Run Twitter-only scrape if pump.fun fails"""
    logger.info("Running Twitter-only scrape...")

    analyzer = TickerAnalyzer(db)

    tweets = await twitter.search_memecoin_terms(max_results=100)

    if not tweets:
        logger.warning("No tweets found")
        return

    logger.info(f"Found {len(tweets)} tweets")

    # Extract pump.fun addresses
    contracts = analyzer.extract_pump_fun_addresses(tweets)
    logger.info(f"Extracted {len(contracts)} pump.fun contracts")

    # Process
    analyzer.process_contracts(contracts)

    # Also extract tickers
    mentions = analyzer.extract_tickers(tweets)
    analyzer.process_mentions(mentions)

    # Show trending
    trending = analyzer.calculate_trending(limit=10)

    if trending:
        logger.info("Top trending:")
        for i, t in enumerate(trending[:5], 1):
            logger.info(f"  {i}. ${t.symbol} - Score: {t.score:.0f}")


async def run_scraper_loop():
    """Run the scraper on a schedule"""
    scheduler = AsyncIOScheduler()

    # Run immediately on start
    await run_scrape_cycle()

    # Schedule regular runs
    scheduler.add_job(
        run_scrape_cycle,
        "interval",
        minutes=settings.scrape_interval_minutes,
        id="scraper",
    )

    scheduler.start()
    logger.info(f"Scraper scheduled to run every {settings.scrape_interval_minutes} minutes")

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


async def run_telegram_bot():
    """Run the Telegram bot"""
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token not configured. Skipping bot startup.")
        return

    bot = TelegramBot()
    await bot.start()

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        await bot.stop()


def run_dashboard():
    """Run the web dashboard"""
    logger.info(f"Starting dashboard at http://{settings.dashboard_host}:{settings.dashboard_port}")
    uvicorn.run(
        "src.dashboard.app:app",
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        reload=False,
    )


async def run_all():
    """Run scraper, dashboard, and bot together"""
    logger.info("Starting Trench Scan...")

    # Initialize database
    init_db()

    # Create tasks
    tasks = [
        asyncio.create_task(run_scraper_loop()),
    ]

    # Add Telegram bot if configured
    if settings.telegram_bot_token:
        tasks.append(asyncio.create_task(run_telegram_bot()))

    # Run dashboard in a separate thread (it's blocking)
    import threading

    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "init":
        print("Initializing database...")
        init_db()
        print("Database initialized successfully.")

    elif command == "scrape":
        print("Running single scrape cycle...")
        init_db()
        asyncio.run(run_scrape_cycle())

    elif command == "dashboard":
        print("Starting web dashboard...")
        init_db()
        run_dashboard()

    elif command == "bot":
        print("Starting Telegram bot...")
        init_db()
        asyncio.run(run_telegram_bot())

    elif command == "run":
        print("Starting Trench Scan (scraper + dashboard + bot)...")
        asyncio.run(run_all())

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
