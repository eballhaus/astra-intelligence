import pandas as pd

def safe_df(df):
    """Phase 2.4 minimal safety wrapper: ensure DataFrame validity."""
    if df is None or not isinstance(df, pd.DataFrame):
        return None
    if df.empty:
        return None
    df = df.copy()
    df = df.dropna(how="all")
    df = df.sort_index()
    return df
