"""Built-in vendor → category rules. Seeded into the vendor_rules DB table on first startup."""

BUILT_IN_RULES: list[tuple[str, str]] = sorted([
    ("uber eats", "food"),
    ("doordash", "food"),
    ("menulog", "food"),
    ("deliveroo", "food"),
    ("mcdonald", "food"),

    ("starbucks", "cafe"),

    ("woolworths", "grocery"),
    ("coles", "grocery"),
    ("aldi", "grocery"),
    ("iga supermarket", "grocery"),

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
