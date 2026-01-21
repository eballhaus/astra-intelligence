
# Phase 2.4 temporary compatibility wrapper
def safe_get_grade(engine, symbol, df=None):
    try:
        if df is not None:
            return engine.get_grade(df=df, symbol=symbol)
        print(f"[RankingEngine] ⚠️ No DataFrame for {symbol}, skipping grade.")
        return None
    except TypeError as e:
        print(f"[RankingEngine] ⚠️ get_grade call signature mismatch for {symbol}: {e}")
        return None
