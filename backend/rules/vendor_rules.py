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

# TODO: add ability for users to add their own rules, e.g. "any transaction with 'woolworths' in the description is categorized as 'food'". This would be in addition to the built-in rules above, which should not be editable by users. User-defined rules should be stored in the database and loaded into memory on startup, and applied after the built-in rules.