import logging
from datetime import datetime
from typing import Optional

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

from src.config import settings
from src.database.models import SessionLocal, Ticker
from src.analyzer.ticker import TickerAnalyzer, TrendingTicker

logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram bot for sending alerts and commands"""

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.app: Optional[Application] = None
        self.bot: Optional[Bot] = None

        if self.token:
            self.bot = Bot(token=self.token)

    async def start(self):
        """Start the bot with command handlers"""
        if not self.token:
            logger.warning("Telegram bot token not configured")
            return

        self.app = Application.builder().token(self.token).build()

        # Add command handlers
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("trending", self.cmd_trending))
        self.app.add_handler(CommandHandler("new", self.cmd_new))
        self.app.add_handler(CommandHandler("stats", self.cmd_stats))
        self.app.add_handler(CommandHandler("ticker", self.cmd_ticker))

        logger.info("Telegram bot started")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def stop(self):
        """Stop the bot"""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        if not update.message:
            return
        welcome_msg = (
            "*Trench Scan Bot*\n\n"
            "Your memecoin radar is active.\n\n"
            "*Commands:*\n"
            "/trending - Top trending tickers\n"
            "/new - New discoveries\n"
            "/stats - Overall statistics\n"
            "/ticker <SYMBOL> - Ticker details\n"
            "/help - Show help"
        )
        await update.message.reply_text(welcome_msg, parse_mode="Markdown")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        if not update.message:
            return
        help_msg = (
            "*Trench Scan Commands*\n\n"
            "/trending - Show top 10 trending tickers by velocity\n"
            "/new - Show newly discovered tickers (last 24h)\n"
            "/stats - Show overall statistics\n"
            "/ticker SYMBOL - Get details for a specific ticker\n\n"
            "You'll also receive automatic alerts for:\n"
            "- New ticker discoveries\n"
            "- Velocity spikes\n"
            "- High engagement tweets"
        )
        await update.message.reply_text(help_msg, parse_mode="Markdown")

    async def cmd_trending(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /trending command"""
        if not update.message:
            return
        db = SessionLocal()
        try:
            analyzer = TickerAnalyzer(db)
            trending = analyzer.calculate_trending(limit=10)

            if not trending:
                await update.message.reply_text("No trending tickers yet. Run the scraper first.")
                return

            msg = "*Trending Tickers*\n\n"
            for i, t in enumerate(trending, 1):
                velocity_indicator = "+" if t.velocity > 0 else ""
                msg += (
                    f"{i}. *${t.symbol}*\n"
                    f"   1h: {t.mentions_1h} | 24h: {t.mentions_24h}\n"
                    f"   Velocity: {velocity_indicator}{t.velocity:.1f}x | Score: {t.score:.0f}\n\n"
                )

            await update.message.reply_text(msg, parse_mode="Markdown")
        finally:
            db.close()

    async def cmd_new(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /new command"""
        if not update.message:
            return
        db = SessionLocal()
        try:
            analyzer = TickerAnalyzer(db)
            new_tickers = analyzer.get_new_tickers(hours=24)

            if not new_tickers:
                await update.message.reply_text("No new tickers discovered in the last 24h.")
                return

            msg = "*New Discoveries (24h)*\n\n"
            for ticker in new_tickers[:15]:
                time_str = ticker.first_seen.strftime("%H:%M")
                msg += f"*${ticker.symbol}* - {ticker.total_mentions} mentions (seen at {time_str})\n"

            await update.message.reply_text(msg, parse_mode="Markdown")
        finally:
            db.close()

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        if not update.message:
            return
        from sqlalchemy import func
        from datetime import timedelta
        from src.database.models import Mention

        db = SessionLocal()
        try:
            now = datetime.utcnow()

            total_tickers = db.query(func.count(Ticker.id)).scalar()
            total_mentions = db.query(func.count(Mention.id)).scalar()

            mentions_1h = (
                db.query(func.count(Mention.id))
                .filter(Mention.timestamp >= now - timedelta(hours=1))
                .scalar()
            )

            mentions_24h = (
                db.query(func.count(Mention.id))
                .filter(Mention.timestamp >= now - timedelta(hours=24))
                .scalar()
            )

            msg = (
                "*Trench Scan Statistics*\n\n"
                f"Total Tickers: *{total_tickers}*\n"
                f"Total Mentions: *{total_mentions}*\n"
                f"Mentions (1h): *{mentions_1h}*\n"
                f"Mentions (24h): *{mentions_24h}*\n\n"
                f"Last updated: {now.strftime('%Y-%m-%d %H:%M UTC')}"
            )

            await update.message.reply_text(msg, parse_mode="Markdown")
        finally:
            db.close()

    async def cmd_ticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ticker <SYMBOL> command"""
        if not update.message:
            return
        if not context.args:
            await update.message.reply_text("Usage: /ticker SYMBOL\nExample: /ticker PEPE")
            return

        symbol = context.args[0].upper().replace("$", "")

        db = SessionLocal()
        try:
            ticker = db.query(Ticker).filter(Ticker.symbol == symbol).first()

            if not ticker:
                await update.message.reply_text(f"Ticker ${symbol} not found.")
                return

            msg = (
                f"*${ticker.symbol}*\n\n"
                f"First seen: {ticker.first_seen.strftime('%Y-%m-%d %H:%M')}\n"
                f"Last seen: {ticker.last_seen.strftime('%Y-%m-%d %H:%M')}\n"
                f"Total mentions: *{ticker.total_mentions}*\n"
            )

            if ticker.contract_address:
                msg += f"Contract: `{ticker.contract_address}`\n"
            if ticker.chain:
                msg += f"Chain: {ticker.chain}\n"

            await update.message.reply_text(msg, parse_mode="Markdown")
        finally:
            db.close()

    async def send_alert(self, message: str, chat_id: Optional[str] = None):
        """Send an alert message to the configured chat"""
        if not self.bot:
            logger.warning("Cannot send alert - bot not configured")
            return

        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.warning("Cannot send alert - no chat_id configured")
            return

        try:
            await self.bot.send_message(
                chat_id=target_chat,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            logger.info(f"Alert sent to chat {target_chat}")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    async def send_new_ticker_alert(self, ticker: Ticker, first_tweet_text: str):
        """Send alert for newly discovered ticker"""
        msg = (
            f"*NEW TICKER DETECTED*\n\n"
            f"*${ticker.symbol}*\n\n"
            f"_{first_tweet_text[:200]}{'...' if len(first_tweet_text) > 200 else ''}_\n\n"
            f"First seen: {ticker.first_seen.strftime('%H:%M UTC')}"
        )
        await self.send_alert(msg)

    async def send_trending_alert(self, ticker: TrendingTicker):
        """Send alert for trending ticker"""
        msg = (
            f"*TRENDING ALERT*\n\n"
            f"*${ticker.symbol}* is gaining momentum!\n\n"
            f"Mentions (1h): {ticker.mentions_1h}\n"
            f"Mentions (24h): {ticker.mentions_24h}\n"
            f"Velocity: +{ticker.velocity:.1f}x\n"
            f"Score: {ticker.score:.0f}"
        )
        await self.send_alert(msg)
