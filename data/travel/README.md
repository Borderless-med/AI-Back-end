# Travel FAQ Seed (Plain Explanation)

This folder starts your travel helper. You have a simple CSV: `faq_seed.csv`.
Each row is one common question with a short, clear answer.

## What You Do Next (One Step At A Time)
1. Review the 20 starter rows. Edit wording to fit your voice.
2. Create a Supabase table called `travel_faq` with these columns:
   - `id` (int)
   - `category` (text)
   - `question` (text)
   - `answer` (text)
   - `tags` (text) – store as a single string for now (pipe separated)
   - `last_updated` (date)
   - Later: add `embedding` (vector) when you are ready for semantic search.
3. Import the CSV (Supabase Dashboard → Table Editor → Import).
4. (Optional later) Add more rows until you reach ~100.
5. Build a small retrieval function: find the closest matching question by simple keyword or embedding.
6. Return the answer directly in a new travel flow (no expensive model call needed for these).

## Why This Helps
- Fast, consistent replies for border/travel questions.
- Easy to keep accurate: just update this CSV / table.
- You only move to “embedding” when you feel ready; not required today.

## Updating Answers
If rules change (e.g. train schedule):
- Update the row answer.
- Bump `last_updated` date.

## Suggested Categories To Expand
- preparation
- timing
- travel_time
- travel_cost
- travel_options
- immigration
- pitfalls
- ciq_to_clinic
- home_to_ciq

Keep answers short and practical.

## Adding Embeddings Later (Preview)
You will:
- Add a new `embedding` column (vector type) in Supabase.
- Run a script to fill it using your existing embedding model.
- Use cosine similarity to pick the best row.

For now, **plain keyword** matching is enough while you grow the list.

## Next Optional Step
Ask me to create a simple ingestion/embedding script when you are ready.
