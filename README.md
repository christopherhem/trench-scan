# Trench Scan

Viral trend scraper for memecoin ticker detection. Monitors Twitter/X for emerging memecoin mentions, tracks trending velocity, and sends alerts via Telegram.

## Features

- **Twitter Scraping**: Uses Nitter instances to scrape tweets without API costs
- **Ticker Detection**: Extracts $TICKER mentions, filters out known coins
- **Trending Analysis**: Calculates mention velocity and trending scores
- **Web Dashboard**: Real-time view of trending tickers
- **Telegram Bot**: Alerts and commands for monitoring on the go
- **Local First**: Runs entirely on your local machine

## Quick Start

### 1. Install Dependencies

```bash
cd trench-scan
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings (Telegram bot token, etc.)
```

### 3. Initialize Database

```bash
python main.py init
```

### 4. Run

```bash
# Run everything (scraper + dashboard + telegram bot)
python main.py run

# Or run components separately:
python main.py scrape      # Single scrape cycle
python main.py dashboard   # Web dashboard only
python main.py bot         # Telegram bot only
```

### 5. Access Dashboard

Open http://127.0.0.1:8000 in your browser.

## Telegram Bot Setup

1. Create a bot with [@BotFather](https://t.me/botfather)
2. Get your bot token
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_CHAT_ID=your_chat_id
   ```
4. Start a chat with your bot and send `/start`

### Bot Commands

- `/trending` - Top trending tickers
- `/new` - New discoveries (24h)
- `/stats` - Overall statistics
- `/ticker SYMBOL` - Ticker details

## Configuration

Edit `.env` to customize:

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRAPE_INTERVAL_MINUTES` | 5 | How often to scrape |
| `MIN_MENTIONS_THRESHOLD` | 3 | Min mentions to track |
| `TRENDING_VELOCITY_THRESHOLD` | 5 | Velocity spike alert threshold |
| `DASHBOARD_PORT` | 8000 | Web dashboard port |

## API Endpoints

- `GET /` - Web dashboard
- `GET /api/trending` - Trending tickers JSON
- `GET /api/ticker/{symbol}` - Ticker details
- `GET /api/stats` - Overall statistics

## Architecture

```
trench-scan/
├── src/
│   ├── scraper/       # Twitter scraping via Nitter
│   ├── analyzer/      # Ticker extraction & trending
│   ├── database/      # SQLite models
│   ├── dashboard/     # FastAPI web UI
│   └── bots/          # Telegram bot
├── main.py            # Entry point
└── requirements.txt
```

## Notes

- Nitter instances can be unstable. The scraper automatically tries multiple instances.
- Rate limiting is built-in to avoid getting blocked.
- Data is stored locally in SQLite (`trench_scan.db`).

## Disclaimer

This tool is for informational purposes only. Do your own research before trading. Not financial advice.
