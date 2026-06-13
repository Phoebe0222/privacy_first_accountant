"""
Shared Australian individual income tax calculation helpers.

Used by:
  - backend/services/tax_agent.py  (/ai-estimate)
  - backend/routers/deductions.py  (/estimate)

Tax brackets: Stage 3, effective FY2024-25 onward.
"""

TAX_BRACKETS = [
    (18_200,       0.00),
    (45_000,       0.16),
    (135_000,      0.30),
    (190_000,      0.37),
    (float("inf"), 0.45),
]

LOW_INCOME_OFFSET_MAX = 700
MEDICARE_LEVY = 0.02

# Medicare Levy Surcharge — singles thresholds/rates, FY2024-25 (review annually for indexation).
# Only applies to high-income earners who do NOT hold an appropriate level of private hospital cover.
MLS_TIERS = [
    (97_000,       0.000),
    (113_000,      0.010),
    (151_000,      0.0125),
    (float("inf"), 0.015),
]


def income_tax(taxable_income: float) -> float:
    """Progressive tax across all brackets up to taxable_income."""
    tax = 0.0
    lower = 0.0
    for threshold, rate in TAX_BRACKETS:
        if taxable_income <= lower:
            break
        tax += (min(taxable_income, threshold) - lower) * rate
        lower = threshold
    return tax


def medicare_levy_surcharge(taxable_income: float, has_private_hospital_cover: bool) -> float:
    if has_private_hospital_cover or taxable_income <= 0:
        return 0.0
    for threshold, rate in MLS_TIERS:
        if taxable_income <= threshold:
            return round(taxable_income * rate, 2)
    return 0.0


def calc_tax(taxable_income: float, has_private_hospital_cover: bool = False) -> float:
    if taxable_income <= 0:
        return 0.0
    lito = max(0.0, LOW_INCOME_OFFSET_MAX - max(0.0, taxable_income - 37_500) * 0.05)
    medicare = taxable_income * MEDICARE_LEVY
    mls = medicare_levy_surcharge(taxable_income, has_private_hospital_cover)
    return max(0.0, round(income_tax(taxable_income) - lito + medicare + mls, 2))
