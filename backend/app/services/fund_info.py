"""Fund information CRUD service."""

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.fund import Fund, FundHolding


class FundInfoService:
    """Manages fund metadata and holdings in the database."""

    async def add_fund(
        self,
        session: AsyncSession,
        fund_code: str,
        fund_name: str,
        fund_type: str,
        last_nav: float | None = None,
        nav_date: str | None = None,
    ) -> Fund:
        fund = Fund(
            fund_code=fund_code,
            fund_name=fund_name,
            fund_type=fund_type,
            last_nav=last_nav,
            nav_date=nav_date,
        )
        session.add(fund)
        await session.commit()
        return fund

    async def get_fund(self, session: AsyncSession, fund_code: str) -> Fund | None:
        return await session.get(Fund, fund_code)

    async def get_all_funds(self, session: AsyncSession) -> list[Fund]:
        result = await session.execute(select(Fund))
        return list(result.scalars().all())

    async def update_nav(
        self, session: AsyncSession, fund_code: str, nav: float, nav_date: str
    ) -> None:
        fund = await session.get(Fund, fund_code)
        if fund:
            fund.last_nav = nav
            fund.nav_date = nav_date
            await session.commit()

    async def update_holdings(
        self,
        session: AsyncSession,
        fund_code: str,
        holdings_data: list[dict],
        report_date: str,
    ) -> None:
        # Delete old holdings for this fund
        await session.execute(
            delete(FundHolding).where(FundHolding.fund_code == fund_code)
        )

        # Insert new holdings
        for h in holdings_data:
            holding = FundHolding(
                fund_code=fund_code,
                stock_code=h["stock_code"],
                stock_name=h["stock_name"],
                holding_ratio=h["holding_ratio"],
                report_date=report_date,
            )
            session.add(holding)

        await session.commit()

    async def get_holdings(
        self, session: AsyncSession, fund_code: str
    ) -> list[FundHolding]:
        result = await session.execute(
            select(FundHolding).where(FundHolding.fund_code == fund_code)
        )
        return list(result.scalars().all())


fund_info_service = FundInfoService()
