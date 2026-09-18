# ScholarSearch

A hybrid information retrieval engine for discovering Indian government and
private scholarships/schemes — IR mini-project.

## The core idea

Most scholarship search tools are either a static filtered list or plain
keyword search with no sense of whether the user actually qualifies.
ScholarSearch ranks results with:

```
hybrid_score = alpha * text_relevance(query, scheme)
             + (1 - alpha) * eligibility_match(profile, scheme)
```

- **text_relevance** — SQLite FTS5's BM25 ranking over scheme name,
  provider, level, category, description and tags, after a domain-specific
  query-expansion pass (e.g. "dalit" -> SC, "adivasi" -> ST, "poor" -> EWS).
- **eligibility_match** — a structured 0-1 score built from how well the
  user's category / gender / state / income / marks / education level line
  up with each scheme's stated eligibility.
- **alpha** shifts automatically: 1.0 for a pure text query with no profile,
  0.35 (favouring eligibility) once a profile is supplied.

## Project structure

```
scholarsearch/
  backend/
    app.py             Flask API (search, filters, stats, health)
    schemes_data.py    45 real scholarship/scheme entries (curated)
    seed_data.py       Builds scholarsearch.db with FTS5 + triggers
    requirements.txt
  frontend/
    index.html          Single-file vanilla JS UI, no build step needed
```

## Running it

```bash
cd backend
pip install -r requirements.txt
python3 seed_data.py        # builds scholarsearch.db (run once, or after editing schemes_data.py)
python3 app.py               # starts API on http://127.0.0.1:5001
```

Then open `frontend/index.html` directly in a browser, or serve it:
`python3 -m http.server 3000` from the `frontend/` folder, then visit
`http://localhost:3000`.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/search` | `{query, profile}` -> hybrid-ranked results |
| GET | `/api/schemes` | Paginated list of all schemes |
| GET | `/api/schemes/<id>` | Single scheme detail |
| GET | `/api/filters` | Distinct categories/states/levels for dropdowns |
| GET | `/api/stats` | Counts by category / level / state |
| GET | `/api/health` | DB connectivity check |

## What's original here (for the report's Methodology section)

1. **Hybrid text + eligibility ranking** — the core contribution. Worth a
   whole section with a worked example: run the same query with and
   without a profile and show how ranking changes.
2. **Domain-specific query expansion** for scholarship vernacular rather
   than generic English synonyms.
3. **Multi-category eligibility parsing** — schemes like "SC/ST/PWD" list
   several eligible categories; the matcher splits and checks overlap
   rather than exact string equality.

## Known limitations (good for a "Limitations & Future Work" section)

- Eligibility figures are commonly-cited approximations for demo purposes,
  not live government data. A real deployment should sync from the
  National Scholarship Portal (scholarships.gov.in) and state DBT portals.
- 45 schemes demonstrates the retrieval/ranking logic end-to-end; scaling
  to the full 1,000+ schemes available would need a scraper/ETL pipeline.
- No user accounts/saved searches — out of scope for the IR focus here.

## Suggested evaluation approach

Build a small ground-truth test set: pick 10-15 synthetic student profiles,
manually mark which schemes *should* rank highly for each, then compute
precision@5 for hybrid_score vs BM25-only vs eligibility-only. Gives a
legitimate, reproducible metrics table and demonstrates why hybrid helps.
