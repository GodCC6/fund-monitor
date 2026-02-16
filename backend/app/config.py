"""Application configuration."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "fund_monitor.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# Cache settings (in-memory, replaces Redis for MVP)
STOCK_CACHE_TTL = 60  # seconds
ESTIMATE_CACHE_TTL = 30  # seconds

# Market data settings
MARKET_DATA_INTERVAL = 30  # seconds between stock quote fetches
TRADING_START = "09:30"
TRADING_END = "15:00"

# Ensure data directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
