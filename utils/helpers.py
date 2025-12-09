"""Utility Helpers"""
def safe_mean(values):
    return sum(values)/len(values) if values else 0
