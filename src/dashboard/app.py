import logging
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.database.models import get_db, Ticker, Mention, TrendSnapshot
from src.analyzer.ticker import TickerAnalyzer
from src.config import settings

logger = logging.getLogger(__name__)

# Setup paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""

    app = FastAPI(
        title="Trench Scan",
        description="Viral Trend Scraper for Memecoin Detection",
        version="0.1.0",
    )

    # Create directories if they don't exist
    TEMPLATES_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)

    # Setup templates
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, db: Session = Depends(get_db)):
        """Main dashboard view"""
        analyzer = TickerAnalyzer(db)

        # Get trending tickers
        trending = analyzer.calculate_trending(limit=20)

        # Get new tickers (last 24h)
        new_tickers = analyzer.get_new_tickers(hours=24)

        # Get stats
        total_tickers = db.query(func.count(Ticker.id)).scalar()
        total_mentions = db.query(func.count(Mention.id)).scalar()

        now = datetime.utcnow()
        mentions_24h = (
            db.query(func.count(Mention.id))
            .filter(Mention.timestamp >= now - timedelta(hours=24))
            .scalar()
        )

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "trending": trending,
                "new_tickers": new_tickers,
                "stats": {
                    "total_tickers": total_tickers,
                    "total_mentions": total_mentions,
                    "mentions_24h": mentions_24h,
                },
                "last_updated": now.strftime("%Y-%m-%d %H:%M UTC"),
            },
        )

    @app.get("/api/trending")
    async def api_trending(limit: int = 20, db: Session = Depends(get_db)):
        """API endpoint for trending tickers"""
        analyzer = TickerAnalyzer(db)
        trending = analyzer.calculate_trending(limit=limit)

        return {
            "trending": [
                {
                    "symbol": t.symbol,
                    "mentions_1h": t.mentions_1h,
                    "mentions_24h": t.mentions_24h,
                    "velocity": round(t.velocity, 2),
                    "score": round(t.score, 2),
                    "first_seen": t.first_seen.isoformat(),
                    "latest_tweet": {
                        "text": t.latest_tweet.text if t.latest_tweet else None,
                        "url": t.latest_tweet.url if t.latest_tweet else None,
                        "author": t.latest_tweet.author_username if t.latest_tweet else None,
                    } if t.latest_tweet else None,
                }
                for t in trending
            ],
            "updated_at": datetime.utcnow().isoformat(),
        }

    @app.get("/api/ticker/{symbol}")
    async def api_ticker_detail(symbol: str, db: Session = Depends(get_db)):
        """Get detailed info for a specific ticker"""
        ticker = db.query(Ticker).filter(Ticker.symbol == symbol.upper()).first()

        if not ticker:
            return {"error": "Ticker not found"}

        # Get recent mentions
        mentions = (
            db.query(Mention)
            .filter(Mention.ticker_id == ticker.id)
            .order_by(Mention.timestamp.desc())
            .limit(50)
            .all()
        )

        # Get trend history
        snapshots = (
            db.query(TrendSnapshot)
            .filter(TrendSnapshot.ticker_id == ticker.id)
            .order_by(TrendSnapshot.timestamp.desc())
            .limit(100)
            .all()
        )

        return {
            "ticker": {
                "symbol": ticker.symbol,
                "first_seen": ticker.first_seen.isoformat(),
                "last_seen": ticker.last_seen.isoformat(),
                "total_mentions": ticker.total_mentions,
                "contract_address": ticker.contract_address,
                "chain": ticker.chain,
            },
            "mentions": [
                {
                    "text": m.tweet_text,
                    "url": m.tweet_url,
                    "author": m.author_username,
                    "likes": m.likes,
                    "retweets": m.retweets,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in mentions
            ],
            "trend_history": [
                {
                    "timestamp": s.timestamp.isoformat(),
                    "mentions_1h": s.mentions_1h,
                    "score": round(s.score, 2),
                }
                for s in snapshots
            ],
        }

    @app.get("/api/stats")
    async def api_stats(db: Session = Depends(get_db)):
        """Get overall statistics"""
        now = datetime.utcnow()

        total_tickers = db.query(func.count(Ticker.id)).scalar()
        total_mentions = db.query(func.count(Mention.id)).scalar()

        new_tickers_24h = (
            db.query(func.count(Ticker.id))
            .filter(Ticker.first_seen >= now - timedelta(hours=24))
            .scalar()
        )

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

        return {
            "total_tickers": total_tickers,
            "total_mentions": total_mentions,
            "new_tickers_24h": new_tickers_24h,
            "mentions_1h": mentions_1h,
            "mentions_24h": mentions_24h,
            "updated_at": now.isoformat(),
        }

    return app


# Create app instance
app = create_app()
