import threading
import time


def warmup():
    from core.hardware_accel import pin_device
    pin_device()

    from concurrent.futures import ThreadPoolExecutor

    """Preload slow components asynchronously."""
    try:
        from core.cache_manager import CacheManager
        from universe import universe_builder

        universe_builder.build_universe(source="cached")
        executor = ThreadPoolExecutor(max_workers=4)
        tasks = [
            lambda: universe_builder.build_universe(source="cached"),
            lambda: CacheManager.get_or_set("ranked_results", lambda: None),
        ]
        [executor.submit(t) for t in tasks]
        executor.shutdown(wait=False)

        CacheManager.get_or_set("ranked_results", lambda: None)
        time.sleep(1)
    except Exception as e:
        print(f"[Preload] Warning: {e}")


def start_async_preload():
    t = threading.Thread(target=warmup, daemon=True)
    t.start()
