"""Small helpers shared by several modules."""


def escape_like(text):
    """Escape % and _ so a search text is matched literally inside a LIKE pattern."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_page(args, total, per_page):
    """Return (page, pages) from ?page=N, kept inside the valid range."""
    pages = max(1, (total + per_page - 1) // per_page)
    try:
        page = int(args.get("page", 1))
    except ValueError:
        page = 1
    return min(max(page, 1), pages), pages


def to_int(value):
    """Convert text to int, or return None if it is not a whole number."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
