"""Portfolio management service."""

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.portfolio import Portfolio, PortfolioFund


class PortfolioService:
    """Manages user portfolios and their fund holdings."""

    async def create_portfolio(self, session: AsyncSession, name: str) -> Portfolio:
        portfolio = Portfolio(name=name)
        session.add(portfolio)
        await session.commit()
        return portfolio

    async def get_portfolio(
        self, session: AsyncSession, portfolio_id: int
    ) -> Portfolio | None:
        return await session.get(Portfolio, portfolio_id)

    async def list_portfolios(self, session: AsyncSession) -> list[Portfolio]:
        result = await session.execute(select(Portfolio))
        return list(result.scalars().all())

    async def delete_portfolio(self, session: AsyncSession, portfolio_id: int) -> None:
        await session.execute(
            delete(PortfolioFund).where(PortfolioFund.portfolio_id == portfolio_id)
        )
        await session.execute(delete(Portfolio).where(Portfolio.id == portfolio_id))
        await session.commit()

    async def rename_portfolio(
        self, session: AsyncSession, portfolio_id: int, name: str
    ) -> Portfolio | None:
        portfolio = await session.get(Portfolio, portfolio_id)
        if portfolio is None:
            return None
        portfolio.name = name
        await session.commit()
        return portfolio

    async def add_fund(
        self,
        session: AsyncSession,
        portfolio_id: int,
        fund_code: str,
        shares: float,
        cost_nav: float,
    ) -> PortfolioFund:
        pf = PortfolioFund(
            portfolio_id=portfolio_id,
            fund_code=fund_code,
            shares=shares,
            cost_nav=cost_nav,
        )
        session.add(pf)
        await session.commit()
        return pf

    async def get_portfolio_funds(
        self, session: AsyncSession, portfolio_id: int
    ) -> list[PortfolioFund]:
        result = await session.execute(
            select(PortfolioFund).where(PortfolioFund.portfolio_id == portfolio_id)
        )
        return list(result.scalars().all())

    async def remove_fund(
        self, session: AsyncSession, portfolio_id: int, fund_code: str
    ) -> None:
        await session.execute(
            delete(PortfolioFund).where(
                PortfolioFund.portfolio_id == portfolio_id,
                PortfolioFund.fund_code == fund_code,
            )
        )
        await session.commit()


portfolio_service = PortfolioService()
