"""Fund NAV estimation engine.

Calculates real-time fund NAV estimates based on holdings and stock quotes.

Algorithm:
    est_change_pct = Σ (holding_ratio_i * stock_change_pct_i)
    est_nav = last_nav * (1 + est_change_pct / 100)
"""

from typing import Any


class FundEstimator:
    """Calculates fund NAV estimates from holdings and real-time stock quotes."""

    def calculate_estimate(
        self,
        holdings: list[dict[str, Any]],
        stock_quotes: dict[str, dict[str, Any]],
        last_nav: float,
    ) -> dict[str, Any]:
        """Calculate estimated NAV change for a fund.

        Args:
            holdings: List of {stock_code, stock_name, holding_ratio}.
            stock_quotes: Dict of stock_code -> {price, change_pct, name}.
            last_nav: The fund's last published NAV.

        Returns:
            {est_nav, est_change_pct, coverage, details: [{stock_code, stock_name,
             holding_ratio, change_pct, contribution}]}
        """
        est_change_pct = 0.0
        coverage = 0.0
        details = []

        for holding in holdings:
            stock_code = holding["stock_code"]
            quote = stock_quotes.get(stock_code)
            if quote is None:
                continue

            ratio = holding["holding_ratio"]
            change_pct = quote["change_pct"]
            contribution = ratio * change_pct

            est_change_pct += contribution
            coverage += ratio

            details.append(
                {
                    "stock_code": stock_code,
                    "stock_name": holding["stock_name"],
                    "holding_ratio": ratio,
                    "price": quote["price"],
                    "change_pct": change_pct,
                    "contribution": contribution,
                }
            )

        est_nav = last_nav * (1 + est_change_pct / 100)

        return {
            "est_nav": round(est_nav, 4),
            "est_change_pct": round(est_change_pct, 4),
            "coverage": round(coverage, 4),
            "last_nav": last_nav,
            "details": details,
        }


# Global instance
fund_estimator = FundEstimator()
