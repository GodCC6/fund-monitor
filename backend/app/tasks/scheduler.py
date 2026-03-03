"""Background task scheduler for periodic market data updates."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# China Standard Time (UTC+8) — used for all trading-hours checks and cron triggers
_CST = timezone(timedelta(hours=8))

from app.services.market_data import market_data_service
from app.services.cache import stock_cache
from app.services.fund_info import fund_info_service
from app.services.estimator import fund_estimator
from app.models.database import async_session_factory
from app.models.fund import FundEstimateSnapshot
from app.config import MARKET_DATA_INTERVAL

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Retry configuration for stock quote fetches
_STOCK_FETCH_MAX_RETRIES = 3
_STOCK_FETCH_BASE_DELAY = 1.0  # seconds; doubled on each retry


async def _fetch_quotes_with_retry(stock_codes: list[str]) -> dict:
    """Fetch stock quotes with exponential backoff retries on transient failure.

    An empty result when codes were requested is treated as a transient failure
    and retried up to _STOCK_FETCH_MAX_RETRIES times with exponential backoff.
    Delays: base_delay * 2^0, base_delay * 2^1, ... (no sleep after last attempt).
    """
    if not stock_codes:
        return {}
    for attempt in range(_STOCK_FETCH_MAX_RETRIES):
        quotes = market_data_service.get_stock_quotes(stock_codes)
        if quotes:
            if attempt > 0:
                logger.info(
                    f"Stock quote fetch succeeded on attempt {attempt + 1}/{_STOCK_FETCH_MAX_RETRIES}"
                )
            return quotes
        # Empty result: retry if attempts remain
        if attempt < _STOCK_FETCH_MAX_RETRIES - 1:
            delay = _STOCK_FETCH_BASE_DELAY * (2**attempt)
            logger.warning(
                f"Stock quote fetch returned empty "
                f"(attempt {attempt + 1}/{_STOCK_FETCH_MAX_RETRIES}), "
                f"retrying in {delay:.1f}s"
            )
            await asyncio.sleep(delay)
        else:
            logger.error(
                f"Stock quote fetch failed after {_STOCK_FETCH_MAX_RETRIES} attempts, giving up"
            )
    return {}


def is_trading_hours() -> bool:
    """Check if current time is within A-share trading hours (China Standard Time)."""
    now = datetime.now(_CST)
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

            quotes = await _fetch_quotes_with_retry(list(all_stock_codes))
            for code, quote in quotes.items():
                # Ensure cache key always uses 6-digit zero-padded pure numeric code
                normalized = str(code).zfill(6)
                stock_cache.set(f"stock:{normalized}", quote)

            logger.info(f"Updated {len(quotes)} stock quotes")

            # Save estimate snapshots
            # Always use CST timezone so times align with East Money index times
            now = datetime.now(_CST)
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
                        "stock_code": str(h.stock_code).zfill(6),
                        "stock_name": h.stock_name,
                        "holding_ratio": h.holding_ratio,
                    }
                    for h in holdings
                ]
                estimate = fund_estimator.calculate_estimate(
                    holdings_data, quotes, fund.last_nav
                )

                # Skip snapshot when no quotes matched holdings (coverage=0):
                # saving est_change_pct=0 would overwrite the last valid snapshot
                # with misleading zero data.
                if estimate["coverage"] <= 0:
                    logger.warning(
                        f"Skipping snapshot for {fund.fund_code}: "
                        f"coverage={estimate['coverage']}, quotes={len(quotes)}"
                    )
                    continue

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


async def save_portfolio_snapshots():
    """At market close (15:05 weekdays), record daily portfolio value snapshots."""
    try:
        from app.models.portfolio import PortfolioSnapshot
        from sqlalchemy import delete as sa_delete

        async with async_session_factory() as session:
            from app.services.portfolio import portfolio_service

            portfolios = await portfolio_service.list_portfolios(session)
            today = datetime.now().strftime("%Y-%m-%d")

            for portfolio in portfolios:
                pf_list = await portfolio_service.get_portfolio_funds(session, portfolio.id)
                total_cost = 0.0
                total_value = 0.0

                for pf in pf_list:
                    fund = await fund_info_service.get_fund(session, pf.fund_code)
                    if not fund or not fund.last_nav:
                        continue

                    est_nav = fund.last_nav
                    holdings = await fund_info_service.get_holdings(session, pf.fund_code)
                    if holdings:
                        stock_codes = [str(h.stock_code).zfill(6) for h in holdings]
                        quotes = {
                            k: stock_cache.get(f"stock:{k}")
                            for k in stock_codes
                            if stock_cache.get(f"stock:{k}") is not None
                        }
                        if quotes:
                            holdings_data = [
                                {
                                    "stock_code": str(h.stock_code).zfill(6),
                                    "stock_name": h.stock_name,
                                    "holding_ratio": h.holding_ratio,
                                }
                                for h in holdings
                            ]
                            estimate = fund_estimator.calculate_estimate(
                                holdings_data, quotes, fund.last_nav
                            )
                            est_nav = estimate["est_nav"]

                    total_cost += pf.shares * pf.cost_nav
                    total_value += pf.shares * est_nav

                # Upsert: replace existing snapshot for today
                await session.execute(
                    sa_delete(PortfolioSnapshot).where(
                        PortfolioSnapshot.portfolio_id == portfolio.id,
                        PortfolioSnapshot.snapshot_date == today,
                    )
                )
                session.add(PortfolioSnapshot(
                    portfolio_id=portfolio.id,
                    snapshot_date=today,
                    total_value=round(total_value, 2),
                    total_cost=round(total_cost, 2),
                ))

            await session.commit()
            logger.info(f"Saved portfolio snapshots for {len(portfolios)} portfolios")
    except Exception as e:
        logger.error(f"Failed to save portfolio snapshots: {e}")


async def refresh_all_fund_holdings():
    """Daily: fetch latest quarterly holdings for all tracked funds.

    Only updates a fund's holdings when a newer report_date is found,
    so this is safe to run frequently without unnecessary DB writes.
    """
    try:
        async with async_session_factory() as session:
            funds = await fund_info_service.get_all_funds(session)
            updated = 0
            year = datetime.now(_CST).strftime("%Y")

            for fund in funds:
                # Check what report_date we currently have stored
                current_holdings = await fund_info_service.get_holdings(session, fund.fund_code)
                current_report_date = current_holdings[0].report_date if current_holdings else None

                # Fetch latest holdings from akshare
                new_holdings, new_report_date = market_data_service.get_fund_holdings(
                    fund.fund_code, year
                )
                if not new_holdings:
                    new_holdings, new_report_date = market_data_service.get_fund_holdings(
                        fund.fund_code, str(int(year) - 1)
                    )

                # Only write if we got a newer (or first-time) report
                if new_holdings and new_report_date and new_report_date != current_report_date:
                    await fund_info_service.update_holdings(
                        session, fund.fund_code, new_holdings[:10], new_report_date
                    )
                    updated += 1
                    logger.info(
                        f"Updated holdings for {fund.fund_code}: "
                        f"{current_report_date} → {new_report_date}"
                    )

            logger.info(f"Holdings refresh: updated {updated}/{len(funds)} funds")
    except Exception as e:
        logger.error(f"Failed to refresh fund holdings: {e}")


async def refresh_all_fund_navs():
    """After market close (20:30 weekdays), fetch official NAV for all tracked funds."""
    try:
        async with async_session_factory() as session:
            funds = await fund_info_service.get_all_funds(session)
            updated = 0
            for fund in funds:
                nav_data = market_data_service.get_fund_nav(fund.fund_code)
                if nav_data and nav_data["nav_date"] != fund.nav_date:
                    fund.last_nav = nav_data["nav"]
                    fund.nav_date = nav_data["nav_date"]
                    fund.updated_at = datetime.now().isoformat()
                    updated += 1
            await session.commit()
            logger.info(f"Refreshed official NAV for {updated}/{len(funds)} funds")
    except Exception as e:
        logger.error(f"Failed to refresh fund NAVs: {e}")


def start_scheduler():
    """Start the background scheduler."""
    scheduler.add_job(
        update_stock_quotes,
        trigger=IntervalTrigger(seconds=MARKET_DATA_INTERVAL),
        id="update_stock_quotes",
        replace_existing=True,
    )
    scheduler.add_job(
        save_portfolio_snapshots,
        trigger=CronTrigger(hour=15, minute=5, day_of_week="mon-fri", timezone=_CST),
        id="save_portfolio_snapshots",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_all_fund_navs,
        trigger=CronTrigger(hour=20, minute=30, day_of_week="mon-fri", timezone=_CST),
        id="refresh_all_fund_navs",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_all_fund_holdings,
        trigger=CronTrigger(hour=21, minute=0, day_of_week="mon-fri", timezone=_CST),
        id="refresh_all_fund_holdings",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started, updating every {MARKET_DATA_INTERVAL}s")


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
