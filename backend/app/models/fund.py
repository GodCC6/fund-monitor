"""Fund and FundHolding models."""

from datetime import datetime
from sqlalchemy import String, Float, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.database import Base


class Fund(Base):
    __tablename__ = "fund"

    fund_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    fund_name: Mapped[str] = mapped_column(String(100))
    fund_type: Mapped[str] = mapped_column(String(20))
    last_nav: Mapped[float | None] = mapped_column(Float, nullable=True)
    nav_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[str] = mapped_column(
        String(30), default=lambda: datetime.now().isoformat()
    )


class FundHolding(Base):
    __tablename__ = "fund_holding"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(10), index=True)
    stock_code: Mapped[str] = mapped_column(String(10))
    stock_name: Mapped[str] = mapped_column(String(50))
    holding_ratio: Mapped[float] = mapped_column(Float)
    report_date: Mapped[str] = mapped_column(String(10))
    updated_at: Mapped[str] = mapped_column(
        String(30), default=lambda: datetime.now().isoformat()
    )
