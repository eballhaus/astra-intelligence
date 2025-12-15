"""
Astra Compatibility Bridge
Allows legacy imports like:
    from astra_core.core.api_client import AstraAPI
to map safely to the new folder structure.
"""

import os
import sys

root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root not in sys.path:
    sys.path.insert(0, root)
