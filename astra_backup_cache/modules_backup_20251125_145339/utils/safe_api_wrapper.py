"""
Astra Intelligence - Safe API Wrapper (Flexible)
-----------------------------------------------
Handles:
- timeouts
- connection errors
- non-200 responses
- JSON decode failures
- generic callable protection
"""

import time
import json

try:
    import requests
except ImportError:
    requests = None


def safe_api_call(target, timeout=10, retries=2, delay=1, **kwargs):
    """
    Flexible safety wrapper.

    If `target` is a string:
        - treated as a URL and fetched via GET (if `requests` is available)
        - returns JSON (dict) or None

    If `target` is callable:
        - calls target() and returns its result
        - catches ANY exception and retries

    Returns:
        - Whatever the callable returns, or parsed JSON from HTTP.
        - None on repeated failure.
    """

    for attempt in range(retries + 1):
        try:
            # -----------------------------------------------
            # Case 1: HTTP URL string
            # -----------------------------------------------
            if isinstance(target, str):
                if requests is None:
                    print("[safe_api_call] 'requests' not available for HTTP mode.")
                    return None

                resp = requests.get(target, timeout=timeout, **kwargs)
                if resp.status_code != 200:
                    print(f"[safe_api_call] HTTP {resp.status_code}: {target}")
                    time.sleep(delay)
                    continue

                try:
                    return resp.json()
                except json.JSONDecodeError:
                    print(f"[safe_api_call] JSON decode failed: {target}")
                    time.sleep(delay)
                    continue

            # -----------------------------------------------
            # Case 2: Callable (e.g., fetch_unified)
            # -----------------------------------------------
            else:
                return target()

        except Exception as e:
            print(f"[safe_api_call] Error ({e}) [attempt {attempt + 1}]")
            time.sleep(delay)

    return None
