VALID_CATEGORIES = frozenset({
    "food", "grocery", "transport", "travel", "utilities", "software", "marketing",
    "revenue", "salary", "refund", "office", "subscription", "shopping", "leisure",
    "material", "fee", "cafe", "gym", "medical", "other",
})

INCOME_CATEGORIES = frozenset({"salary", "revenue", "refund"})
# these are built-in rules, which will be overridden by user-defined rules if there are any conflicts.
# They are used as a fallback for categorisation when no user-defined rules match, and also to provide examples of how rules can be defined.
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
