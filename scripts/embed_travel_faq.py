"""Simple starter script to load travel FAQ rows from CSV into Supabase.
Later you can extend this to add embeddings.

Run (after setting environment variables) with:
    python scripts/embed_travel_faq.py

Environment variables needed:
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY

This script:
1. Reads faq_seed.csv
2. Splits pipe-separated tags
3. Upserts rows into a `travel_faq` table (create the table first via dashboard)

Table suggested columns for now:
 id (int, primary key)
 category (text)
 question (text)
 answer (text)
 tags (text[])  <-- You can choose array type or keep as text
 last_updated (date)

Later add:
 embedding (vector)  <-- when ready
"""
import os
import csv
from datetime import date
from supabase import create_client, Client

DEFAULT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "travel", "faq_seed.csv")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise SystemExit("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def derive_flags(tags_list):
    tagset = {t.lower() for t in tags_list}
    return {
        "top10": "top10" in tagset,
        "dynamic": "dynamic" in tagset,
        "link": "link" in tagset,
    }


def load_rows(csv_path: str):
    """Load rows from a loosely formatted CSV where answer field may contain unquoted commas.

    Expected logical columns per line:
      id, category, question, answer (can have commas), tags, last_updated

    We reconstruct answer by joining all middle segments between the third and last two columns.
    """
    rows = []
    with open(csv_path, encoding='utf-8') as f:
        header = f.readline().strip()
        if not header:
            return rows
        # Basic validation of header
        expected = ["id","category","question","answer","tags","last_updated"]
        header_parts = [h.strip().lower() for h in header.split(",")]
        if header_parts[:6] != expected:
            print("Warning: header does not match expected format; proceeding with flexible parse.")
        line_num = 1
        for line in f:
            line_num += 1
            raw = line.strip()
            if not raw:
                continue
            parts = [p for p in raw.split(",")]
            if len(parts) < 6:
                print(f"Skipping line {line_num}: not enough columns ({len(parts)})")
                continue
            try:
                _id = int(parts[0].strip())
            except ValueError:
                print(f"Skipping line {line_num}: invalid id '{parts[0]}'")
                continue
            category = parts[1].strip()
            question = parts[2].strip()
            # answer spans parts[3:-2]
            answer_segments = parts[3:-2]
            answer = ",".join(seg.strip() for seg in answer_segments).strip()
            tags_raw = parts[-2].strip()
            last_updated = parts[-1].strip() or str(date.today())
            tags_list = [t.strip() for t in tags_raw.split("|") if t.strip()]
            flags = derive_flags(tags_list)
            row = {
                "id": _id,
                "category": category,
                "question": question,
                "answer": answer,
                "tags": tags_list,
                "last_updated": last_updated,
                **flags,
            }
            rows.append(row)
    return rows


def upsert_rows(rows):
    # Upsert each row (small dataset). For larger sets, batch operations.
    for row in rows:
        resp = supabase.table("travel_faq").upsert(row, on_conflict="id").execute()
        if resp.data:
            print(f"Upserted id={row['id']}: {row['question'][:40]}...")
        else:
            print(f"No data returned for id={row['id']}")


def main():
    # Allow optional CSV path argument; fallback to default seed file.
    csv_path = DEFAULT_CSV
    if len(os.sys.argv) > 1:
        csv_path = os.sys.argv[1]
    if not os.path.exists(csv_path):
        raise SystemExit(f"CSV path not found: {csv_path}")
    rows = load_rows(csv_path)
    print(f"Loaded {len(rows)} FAQ rows from CSV: {csv_path}")
    upsert_rows(rows)
    print("Done.")

if __name__ == "__main__":
    main()
