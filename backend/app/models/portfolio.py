"""Portfolio and PortfolioFund models."""

from datetime import datetime
from sqlalchemy import String, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.models.database import Base


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)  # "YYYY-MM-DD"
    total_value: Mapped[float] = mapped_column(Float)
    total_cost: Mapped[float] = mapped_column(Float)

    @property
    def profit_pct(self) -> float:
        if self.total_cost <= 0:
            return 0.0
        return (self.total_value - self.total_cost) / self.total_cost * 100


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[str] = mapped_column(
        String(30), default=lambda: datetime.now().isoformat()
    )


class PortfolioFund(Base):
    __tablename__ = "portfolio_fund"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, index=True)
    fund_code: Mapped[str] = mapped_column(String(10))
    shares: Mapped[float] = mapped_column(Float)
    cost_nav: Mapped[float] = mapped_column(Float)
    added_at: Mapped[str] = mapped_column(
        String(30), default=lambda: datetime.now().isoformat()
    )
