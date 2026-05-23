from sqlalchemy.orm import Session

VALID_CATEGORIES = frozenset({
    "food", "transport", "utilities", "software", "marketing",
    "revenue", "salary", "office", "subscription", "other",
})

# Sorted longest-first so more specific patterns win (e.g. "uber eats" before "uber")
BUILT_IN_RULES: list[tuple[str, str]] = sorted([
    ("uber eats", "food"),
    ("doordash", "food"),
    ("menulog", "food"),
    ("deliveroo", "food"),
    ("mcdonald", "food"),
    ("starbucks", "food"),
    ("woolworths", "food"),
    ("coles", "food"),
    ("aldi", "food"),
    ("iga supermarket", "food"),

    ("uber", "transport"),
    ("lyft", "transport"),
    ("didi", "transport"),
    ("ola cabs", "transport"),
    ("go get", "transport"),

    ("amazon web services", "software"),
    ("microsoft azure", "software"),
    ("google cloud", "software"),
    ("facebook ads", "marketing"),
    ("google ads", "marketing"),
    ("australia post", "utilities"),
    ("origin energy", "utilities"),
    ("energy australia", "utilities"),
    ("agl energy", "utilities"),

    ("aws", "software"),
    ("azure", "software"),
    ("digitalocean", "software"),
    ("cloudflare", "software"),
    ("heroku", "software"),
    ("github", "software"),
    ("atlassian", "software"),
    ("slack", "software"),
    ("zoom", "software"),
    ("dropbox", "software"),
    ("notion", "software"),
    ("xero", "software"),
    ("myob", "software"),
    ("shopify", "software"),
    ("wordpress", "software"),

    ("officeworks", "office"),
    ("staples", "office"),
    ("harvey norman", "office"),
    ("jb hi-fi", "office"),

    ("mailchimp", "marketing"),
    ("hubspot", "marketing"),
    ("meta ads", "marketing"),

    ("telstra", "utilities"),
    ("optus", "utilities"),
    ("vodafone", "utilities"),
    ("auspost", "utilities"),
], key=lambda x: len(x[0]), reverse=True)


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
