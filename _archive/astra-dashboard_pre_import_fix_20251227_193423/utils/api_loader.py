import os


def load_api_key(api_name: str) -> str:
    """Safely load an API key from environment variables."""
    key = os.getenv(f"{api_name.upper()}_API_KEY")
    if not key:
        raise ValueError(f"Missing API key for {api_name}")
    return key
