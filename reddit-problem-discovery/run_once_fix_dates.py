import pandas as pd
import os

DATA_DIR = "data"
PROBLEM_IDS_PATH = os.path.join(DATA_DIR, "problem_ids.csv")
PROBLEM_EVIDENCE_PATH = os.path.join(DATA_DIR, "problem_evidence.csv")

def normalize_date(date_str):
    """Normalize dd-mm-yyyy to yyyy-mm-dd"""
    if pd.isna(date_str) or not str(date_str).strip():
        return date_str
    
    date_str = str(date_str).strip()[:10]
    parts = date_str.split('-')
    if len(parts) == 3 and len(parts[0]) == 2 and len(parts[2]) == 4:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str

def fix_csv(filepath, date_columns):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
    
    try:
        df = pd.read_csv(filepath, encoding="utf-8")
        changed = False
        for col in date_columns:
            if col in df.columns:
                original = df[col].copy()
                df[col] = df[col].apply(normalize_date)
                if not df[col].equals(original):
                    changed = True
                    print(f"Normalized dates in {col} of {filepath}")
        
        if changed:
            df.to_csv(filepath, index=False, encoding="utf-8")
            print(f"Saved {filepath}")
        else:
            print(f"No dates needed normalization in {filepath}")
            
    except Exception as e:
        print(f"Error processing {filepath}: {e}")

if __name__ == "__main__":
    fix_csv(PROBLEM_IDS_PATH, ["first_seen_date", "last_seen_date"])
    fix_csv(PROBLEM_EVIDENCE_PATH, ["post_created_date", "added_date"])
    print("Done!")
