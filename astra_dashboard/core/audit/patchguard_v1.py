import os, difflib, sys

def preview_changes(original, modified):
    with open(original) as f1, open(modified) as f2:
        diff = difflib.unified_diff(f1.readlines(), f2.readlines(), fromfile=original, tofile=modified)
        diff_text = ''.join(diff)
        if diff_text.strip():
            print("⚠️ PatchGuard detected pending changes:")
            print(diff_text)
            print("\n✅ Review complete. Apply manually if approved.")
            sys.exit(1)
        else:
            print("✅ No diffs detected.")
