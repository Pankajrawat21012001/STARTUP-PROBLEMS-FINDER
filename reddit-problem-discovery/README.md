# Reddit Problem Discovery Pipeline

A fully automated pipeline that scrapes Reddit for real startup problems, groups them by semantic similarity, scores each problem using AI, stores everything in CSV files, and displays results in a Streamlit dashboard.

## Tech Stack

- **Reddit Scraping:** PRAW
- **Semantic Grouping:** sentence-transformers (all-MiniLM-L6-v2, local CPU)
- **AI Scoring:** Groq API (llama-3.3-70b-versatile)
- **Storage:** CSV files (Excel-compatible, UTF-8)
- **Dashboard:** Streamlit
- **Env vars:** python-dotenv

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy .env.example to .env and fill in your API keys
cp .env.example .env

# 3. Get Reddit API credentials at: https://www.reddit.com/prefs/apps
#    Create app → script type → note client_id and client_secret

# 4. Get Groq API key at: https://console.groq.com (free)

# 5. Run the pipeline
python main.py

# 6. View dashboard
streamlit run dashboard.py
```

## Pipeline Steps

| Step | File | Description |
|------|------|-------------|
| 1 | `step1_scrape.py` | Scrape Reddit posts using PRAW |
| 2 | `step2_noise_filter.py` | Remove low-quality and irrelevant posts |
| 3 | `step3_semantic_group.py` | Group posts into problems using embeddings |
| 4 | `step4_wtp_score.py` | Score willingness-to-pay signals |
| 5 | `step5_groq_score.py` | AI-powered 8-factor problem evaluation |

## Data Files

| File | Description |
|------|-------------|
| `data/raw_posts.csv` | All scraped Reddit posts |
| `data/problem_ids.csv` | Unique problems with metadata |
| `data/problem_evidence.csv` | Link table: problem ↔ post mapping |
| `data/problem_scores.csv` | AI scores per problem per run |

## Configuration

- `config/subreddits.json` — Target subreddits to scrape
- `config/search_phrases.json` — Search phrases for problem discovery
- `config/noise_blocklist.json` — Noise filtering rules and keywords

## Notes

- Safe to re-run anytime — deduplication prevents reprocessing
- All CSV saves happen after each step — crash-safe
- Dashboard works even with empty data files
- No async — everything runs synchronously for simplicity
