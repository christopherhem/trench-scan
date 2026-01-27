from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Float,
    ForeignKey,
    Text,
    Boolean,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime

from src.config import settings

Base = declarative_base()


class Ticker(Base):
    """Discovered ticker symbols"""

    __tablename__ = "tickers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), unique=True, nullable=False, index=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    total_mentions = Column(Integer, default=0)
    is_known_coin = Column(Boolean, default=False)  # BTC, ETH, SOL etc.
    contract_address = Column(String(100), nullable=True)
    chain = Column(String(20), nullable=True)  # solana, eth, base, etc.

    mentions = relationship("Mention", back_populates="ticker")
    snapshots = relationship("TrendSnapshot", back_populates="ticker")

    def __repr__(self):
        return f"<Ticker ${self.symbol}>"


class Mention(Base):
    """Individual tweet mentions of a ticker"""

    __tablename__ = "mentions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker_id = Column(Integer, ForeignKey("tickers.id"), nullable=False)
    tweet_id = Column(String(50), unique=True, nullable=False)
    tweet_text = Column(Text, nullable=False)
    tweet_url = Column(String(200), nullable=True)
    author_username = Column(String(50), nullable=False)
    author_followers = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    retweets = Column(Integer, default=0)
    timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticker = relationship("Ticker", back_populates="mentions")

    def __repr__(self):
        return f"<Mention {self.tweet_id} - ${self.ticker.symbol if self.ticker else 'N/A'}>"


class TrendSnapshot(Base):
    """Point-in-time snapshot of ticker trending data"""

    __tablename__ = "trend_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker_id = Column(Integer, ForeignKey("tickers.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    mentions_1h = Column(Integer, default=0)  # Mentions in last hour
    mentions_24h = Column(Integer, default=0)  # Mentions in last 24h
    velocity = Column(Float, default=0.0)  # Rate of change
    score = Column(Float, default=0.0)  # Trending score

    ticker = relationship("Ticker", back_populates="snapshots")

    def __repr__(self):
        return f"<TrendSnapshot ${self.ticker.symbol if self.ticker else 'N/A'} - {self.score}>"


class Alert(Base):
    """Alerts sent to Telegram/Discord"""

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker_id = Column(Integer, ForeignKey("tickers.id"), nullable=False)
    alert_type = Column(String(50), nullable=False)  # new_ticker, trending, velocity_spike
    message = Column(Text, nullable=False)
    sent_telegram = Column(Boolean, default=False)
    sent_discord = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# Database setup
engine = create_engine(settings.database_url, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
