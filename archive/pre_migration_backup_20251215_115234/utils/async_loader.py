import threading

def async_load_data(loader_fn):
    """Run any data loader function asynchronously in the background."""
    threading.Thread(target=loader_fn, daemon=True).start()
