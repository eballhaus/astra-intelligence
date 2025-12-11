def safe(value, fallback=None):
    return fallback if value is None else value
