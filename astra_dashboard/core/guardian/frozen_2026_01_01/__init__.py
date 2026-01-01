# Safe Guardian Initializer — aligns with GuardianV7 core class
def get_guardian_core():
    """Lazily import GuardianV7 as the Guardian Core."""
    from .guardian_core import GuardianV7
    return GuardianV7
