from sqlalchemy.orm import Session

from backend.rules.vendor_rules import BUILT_IN_RULES, VALID_CATEGORIES, INCOME_CATEGORIES

__all__ = ["BUILT_IN_RULES", "VALID_CATEGORIES", "INCOME_CATEGORIES"]


def _match_rules(vendor: str, rules: list[tuple[str, str]]) -> str | None:
    v = vendor.lower().strip()
    for pattern, category in rules:
        if pattern in v:
            return category
    return None


def resolve_category(vendor: str, llm_category: str, db: Session) -> str:
    """Apply vendor rules to override LLM-assigned category. User rules > built-in rules > LLM."""
    if not vendor:
        return llm_category or "other"

    from backend.models import VendorRule
    user_rules = db.query(VendorRule).all()
    user_rule_pairs: list[tuple[str, str]] = sorted(
        [(r.vendor_pattern.lower().strip(), r.category) for r in user_rules],
        key=lambda x: len(x[0]),
        reverse=True,
    )

    return (
        _match_rules(vendor, user_rule_pairs)
        or _match_rules(vendor, BUILT_IN_RULES)
        or llm_category
        or "other"
    )
