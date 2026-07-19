
"""Engine package.

Legacy Sentinel cleanup used to execute a file-deletion script whenever this
package was imported.  Imports are not a safe ownership boundary for mutable
maintenance work, so the legacy script remains an explicit operator utility
only.  The worker-owned Sentinel adapter records this component as deprecated.
"""

LEGACY_SENTINEL_IMPORT_CLEANUP_DISABLED = True
