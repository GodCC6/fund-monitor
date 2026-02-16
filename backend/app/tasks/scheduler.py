"""Background task scheduler for periodic market data updates."""

import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services.market_data import market_data_service
from app.services.cache import stock_cache
from app.services.fund_info import fund_info_service
from app.services.estimator import fund_estimator
from app.models.database import async_session_factory
from app.models.fund import FundEstimateSnapshot
from app.config import MARKET_DATA_INTERVAL

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def is_trading_hours() -> bool:
    """Check if current time is within A-share trading hours."""
    now = datetime.now()
    # Skip weekends
    if now.weekday() >= 5:
        return False
    current_time = now.strftime("%H:%M")
    # Morning: 09:30-11:30, Afternoon: 13:00-15:00
    return ("09:25" <= current_time <= "11:35") or ("12:55" <= current_time <= "15:05")


async def update_stock_quotes():
    """Fetch and cache real-time stock quotes for all tracked funds."""
    if not is_trading_hours():
        return

    try:
        async with async_session_factory() as session:
            funds = await fund_info_service.get_all_funds(session)
            all_stock_codes = set()
            fund_holdings_map = {}  # fund_code -> holdings list

            for fund in funds:
                holdings = await fund_info_service.get_holdings(session, fund.fund_code)
                fund_holdings_map[fund.fund_code] = holdings
                for h in holdings:
                    all_stock_codes.add(h.stock_code)

            if not all_stock_codes:
                return

            quotes = market_data_service.get_stock_quotes(list(all_stock_codes))
            for code, quote in quotes.items():
                stock_cache.set(f"stock:{code}", quote)

            logger.info(f"Updated {len(quotes)} stock quotes")

            # Save estimate snapshots
            now = datetime.now()
            snapshot_date = now.strftime("%Y-%m-%d")
            snapshot_time = now.strftime("%H:%M")

            for fund in funds:
                if not fund.last_nav:
                    continue
                holdings = fund_holdings_map.get(fund.fund_code, [])
                if not holdings:
                    continue

                holdings_data = [
                    {
                        "stock_code": h.stock_code,
                        "stock_name": h.stock_name,
                        "holding_ratio": h.holding_ratio,
                    }
                    for h in holdings
                ]
                estimate = fund_estimator.calculate_estimate(
                    holdings_data, quotes, fund.last_nav
                )

                snapshot = FundEstimateSnapshot(
                    fund_code=fund.fund_code,
                    est_nav=estimate["est_nav"],
                    est_change_pct=estimate["est_change_pct"],
                    snapshot_time=snapshot_time,
                    snapshot_date=snapshot_date,
                )
                session.add(snapshot)

            await session.commit()
            logger.info(f"Saved estimate snapshots for {len(funds)} funds")

    except Exception as e:
        logger.error(f"Failed to update stock quotes: {e}")


def start_scheduler():
    """Start the background scheduler."""
    scheduler.add_job(
        update_stock_quotes,
        trigger=IntervalTrigger(seconds=MARKET_DATA_INTERVAL),
        id="update_stock_quotes",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started, updating every {MARKET_DATA_INTERVAL}s")


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
