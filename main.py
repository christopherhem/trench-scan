#!/usr/bin/env python3
"""
Trench Scan - Viral Trend Scraper for Memecoin Detection

Usage:
    python main.py scrape          - Run a single scrape cycle
    python main.py dashboard       - Start the web dashboard
    python main.py bot             - Start the Telegram bot
    python main.py run             - Run scraper + dashboard + bot
    python main.py init            - Initialize the database
    python main.py add-account     - Add a Twitter account for scraping
    python main.py check-accounts  - Check status of Twitter accounts
"""

import asyncio
import logging
import sys
import getpass
from datetime import datetime, timedelta

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import settings
from src.database.models import init_db, SessionLocal
from src.scraper.twitter import TwitterScraper
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


async def add_twitter_account():
    """Interactively add a Twitter account for scraping"""
    print("\n=== Add Twitter Account for Scraping ===\n")
    print("Enter your Twitter/X account credentials.")
    print("(Use a burner account, not your main account)\n")

    username = input("Twitter username: ").strip()
    password = getpass.getpass("Twitter password: ")
    email = input("Email for the account: ").strip()
    email_password = getpass.getpass("Email password (optional, press Enter to skip): ")

    scraper = TwitterScraper()
    try:
        await scraper.add_account(username, password, email, email_password or "")
        print(f"\nAccount @{username} added successfully!")
        print("You can now run 'python main.py run' to start scraping.")
    except Exception as e:
        print(f"\nFailed to add account: {e}")
        print("Make sure the credentials are correct and try again.")


async def check_twitter_accounts():
    """Check status of configured Twitter accounts"""
    scraper = TwitterScraper()
    accounts = await scraper.api.pool.accounts_info()

    if not accounts:
        print("\nNo Twitter accounts configured.")
        print("Run 'python main.py add-account' to add one.")
        return

    print("\n=== Twitter Accounts ===\n")
    for acc in accounts:
        status = "Active" if acc["active"] else "Inactive"
        print(f"  @{acc['username']} - {status}")

    active = [a for a in accounts if a["active"]]
    print(f"\nTotal: {len(accounts)} accounts, {len(active)} active")


async def run_scrape_cycle():
    """Run a single scrape and analysis cycle"""
    logger.info("Starting scrape cycle...")

    scraper = TwitterScraper()

    # Check if we have accounts
    if not await scraper.check_accounts():
        logger.error("No Twitter accounts configured. Run 'python main.py add-account' first.")
        return

    db = SessionLocal()

    try:
        analyzer = TickerAnalyzer(db)

        # Scrape memecoin-related tweets
        logger.info("Searching for memecoin tweets...")
        tweets = await scraper.search_memecoin_terms(max_results=100)

        if not tweets:
            logger.warning("No tweets found in this cycle")
            return

        logger.info(f"Found {len(tweets)} tweets")

        # Extract tickers
        mentions = analyzer.extract_tickers(tweets)
        logger.info(f"Extracted {len(mentions)} ticker mentions")

        # Save to database
        counts = analyzer.process_mentions(mentions)

        if counts:
            logger.info(f"Processed tickers: {dict(counts)}")

        # Calculate trending
        trending = analyzer.calculate_trending(limit=10)

        if trending:
            logger.info("Top trending tickers:")
            for i, t in enumerate(trending[:5], 1):
                logger.info(f"  {i}. ${t.symbol} - Score: {t.score:.0f}, 1h: {t.mentions_1h}")

        logger.info("Scrape cycle completed")

    except Exception as e:
        logger.error(f"Scrape cycle failed: {e}")
        raise
    finally:
        db.close()


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

    # Check for Twitter accounts first
    scraper = TwitterScraper()
    if not await scraper.check_accounts():
        logger.warning("No Twitter accounts configured. Scraper will not collect data.")
        logger.warning("Run 'python main.py add-account' to add a Twitter account.")

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

    elif command == "add-account":
        asyncio.run(add_twitter_account())

    elif command == "check-accounts":
        asyncio.run(check_twitter_accounts())

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
