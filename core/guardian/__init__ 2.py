# Guardian stub used by UI dashboards
import os
if os.environ.get("ASTRA_GUARDIAN_SAFE_MODE", "1") == "1":
    def guardian(*args, **kwargs):
        print("[GuardianStub]", *args)
else:
    try:
        from core.guardian.guardian_v7 import GuardianV7, guardian_log  # noqa
    except Exception as e:
        print("[GuardianStub] ⚠️ Guardian import failed:", e)
