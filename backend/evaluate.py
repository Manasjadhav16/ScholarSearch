"""
ScholarSearch IR Evaluation
---------------------------
Evaluates three ranking strategies against a fixed ground-truth test set:

  1. BM25-only       - alpha = 1.0 (pure text relevance, eligibility ignored)
  2. Eligibility-only - alpha = 0.0 (pure eligibility match, text ignored)
  3. Hybrid          - the existing default from search(): alpha = 0.35 when
                        a profile is supplied, else alpha = 1.0 (matches
                        app.py's own behavior)

For each of the 9 ground-truth queries and each strategy we retrieve the
top 10 ranked results and compute Precision, Recall, F1, Precision@5 and
Average Precision (AP). We then report MAP (mean AP across all queries)
and average NDCG@10 per strategy, plus a full per-query breakdown.

Imports scoring logic directly from app.py (expand_query, eligibility_match,
normalize_bm25, preprocess_query, get_db) so this runs standalone against
the SQLite DB, without going through the Flask server.
"""

import math
import sqlite3

from app import (
    expand_query,
    eligibility_match,
    normalize_bm25,
    preprocess_query,
    get_db,
)

TOP_N = 10

# ---------------- GROUND TRUTH TEST SET ----------------

GROUND_TRUTH = [
    {"query": "study abroad masters scholarship", "profile": {}, "relevant": [
        "National Overseas Scholarship for SC/ST/PWD Students", "Fulbright-Nehru Master's Fellowship",
        "Inlaks Shivdasani Scholarship", "JN Tata Endowment for Higher Education",
        "KC Mahindra Scholarship for Post-Graduate Studies Abroad", "Chevening Scholarship",
        "Commonwealth Scholarship for Indian Students", "DAAD Scholarship for Indian Students (Germany)"
    ]},
    {"query": "scholarship for disabled students", "profile": {}, "relevant": [
        "AICTE Saksham Scholarship for Specially-Abled Students",
        "National Fellowship for Students with Disabilities",
        "National Overseas Scholarship for SC/ST/PWD Students",
        "ONGC Scholarship for SC/ST/PWD/Girl Students"
    ]},
    {"query": "scholarship for girls in engineering", "profile": {}, "relevant": [
        "AICTE Pragati Scholarship for Girls", "CBSE Udaan Scheme for Girls",
        "L'Oreal India For Young Women in Science Scholarship",
        "ONGC Scholarship for SC/ST/PWD/Girl Students"
    ]},
    {"query": "scholarship for scheduled caste students", "profile": {}, "relevant": [
        "Post Matric Scholarship for SC Students", "Top Class Education Scheme for SC Students",
        "National Overseas Scholarship for SC/ST/PWD Students",
        "Maharashtra Post-Matric Scholarship (SC/ST/OBC/VJNT/SBC)",
        "ONGC Scholarship for SC/ST/PWD/Girl Students"
    ]},
    {"query": "minority scholarship for school students", "profile": {}, "relevant": [
        "Pre Matric Scholarship for Minorities", "Begum Hazrat Mahal National Scholarship"
    ]},
    {"query": "PhD fellowship for OBC or disabled students", "profile": {}, "relevant": [
        "National Fellowship for OBC Students", "National Fellowship for Students with Disabilities"
    ]},
    {"query": "", "profile": {"category": "SC", "gender": "Male", "state": "All India", "level": "UG", "income": 200000, "percentage": 65}, "relevant": [
        "Post Matric Scholarship for SC Students", "Top Class Education Scheme for SC Students",
        "INSPIRE Scholarship for Higher Education (SHE)", "Reliance Foundation Undergraduate Scholarship",
        "Aditya Birla Scholarship", "ONGC Scholarship for SC/ST/PWD/Girl Students",
        "Sitaram Jindal Foundation Scholarship", "Colgate Keep India Smiling Scholarship",
        "National Talent Search Examination (NTSE) Scholarship",
        "Prime Minister's Scholarship Scheme for Central Armed Police Forces Wards",
        "Google Generation Scholarship (India)"
    ]},
    {"query": "", "profile": {"category": "General", "gender": "Female", "state": "All India", "level": "School", "income": None, "percentage": None}, "relevant": [
        "National Means-cum-Merit Scholarship (NMMS)", "CBSE Udaan Scheme for Girls",
        "Sitaram Jindal Foundation Scholarship", "National Talent Search Examination (NTSE) Scholarship",
        "Central Sector Scheme for Single Girl Child (CBSE)"
    ]},
    {"query": "engineering scholarship", "profile": {"category": "OBC", "gender": "Male", "state": "All India", "level": "UG", "income": None, "percentage": None}, "relevant": [
        "Aditya Birla Scholarship", "Google Generation Scholarship (India)"
    ]},
]


# ---------------- CORE RANKING (mirrors app.py's search() route) ----------------


def _retrieve_rows(cur, query):
    """Reproduce search()'s row-retrieval logic: FTS5 MATCH with a
    sqlite3.OperationalError -> LIKE-per-word fallback, or all schemes when
    no query is given."""
    if not query:
        cur.execute("SELECT *, 0.0 as rank FROM schemes")
        return cur.fetchall()

    fts_query = expand_query(query)
    try:
        cur.execute("""
            SELECT s.*, bm25(schemes_fts) as rank
            FROM schemes_fts
            JOIN schemes s ON schemes_fts.rowid = s.scheme_id
            WHERE schemes_fts MATCH ?
            ORDER BY rank
            LIMIT 100
        """, (fts_query,))
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        rows = []

    if not rows:
        words = preprocess_query(query).split()
        if words:
            conditions = " OR ".join(
                "name LIKE ? OR description LIKE ? OR tags LIKE ?" for _ in words
            )
            params = [f"%{w}%" for w in words for _ in range(3)]
            cur.execute(f"""
                SELECT *, 0.0 as rank FROM schemes
                WHERE {conditions}
                LIMIT 100
            """, params)
            rows = cur.fetchall()

    return rows


def rank_with_alpha(query, profile, alpha, top_n=TOP_N):
    """Rank all schemes for (query, profile) using a fixed alpha weighting
    of text_score vs eligibility_score (hybrid_score = alpha*text +
    (1-alpha)*eligibility), returning the top_n scheme names."""
    db = get_db()
    cur = db.cursor()

    rows = _retrieve_rows(cur, query)
    all_ranks = [r["rank"] for r in rows]
    has_profile = bool(profile)

    scored = []
    for r in rows:
        text_score = normalize_bm25(r["rank"], all_ranks) if query else 0.5
        elig_score = eligibility_match(profile, r) if has_profile else 0.5
        hybrid = alpha * text_score + (1 - alpha) * elig_score
        scored.append((r["name"], hybrid))

    db.close()
    scored.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in scored[:top_n]]


def rank_bm25_only(query, profile):
    """Force alpha=1.0: pure text relevance, eligibility ignored entirely."""
    return rank_with_alpha(query, profile, alpha=1.0)


def rank_eligibility_only(query, profile):
    """Force alpha=0.0: pure eligibility match, text relevance ignored
    entirely. If no query is given, this is just eligibility score alone."""
    return rank_with_alpha(query, profile, alpha=0.0)


def rank_hybrid(query, profile):
    """Existing default behavior from search(): alpha=1.0 with no profile,
    alpha=0.35 with a profile."""
    alpha = 0.35 if profile else 1.0
    return rank_with_alpha(query, profile, alpha=alpha)


STRATEGIES = [
    ("BM25-only", rank_bm25_only),
    ("Eligibility-only", rank_eligibility_only),
    ("Hybrid", rank_hybrid),
]


# ---------------- IR METRICS ----------------


def precision(retrieved, relevant):
    if not retrieved:
        return 0.0
    hits = sum(1 for r in retrieved if r in relevant)
    return hits / len(retrieved)


def recall(retrieved, relevant):
    if not relevant:
        return 0.0
    hits = sum(1 for r in retrieved if r in relevant)
    return hits / len(relevant)


def f1_score(p, r):
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def average_precision(retrieved, relevant):
    """Standard AP: mean of precision@k at each rank k where the item at
    that rank is relevant, normalized by the total number of relevant
    documents (not just those retrieved)."""
    if not relevant:
        return 0.0
    hits = 0
    total = 0.0
    for k, name in enumerate(retrieved, start=1):
        if name in relevant:
            hits += 1
            total += hits / k
    return total / len(relevant)


def ndcg_at_k(retrieved, relevant, k=TOP_N):
    """Binary-relevance NDCG@k."""
    retrieved_k = retrieved[:k]
    dcg = sum(
        1.0 / math.log2(i + 2)
        for i, name in enumerate(retrieved_k)
        if name in relevant
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    if idcg == 0:
        return 0.0
    return dcg / idcg


# ---------------- EVALUATION RUN ----------------


def evaluate():
    per_query_rows = []  # list of dicts: query_idx, query_label, strategy, metrics
    strategy_aps = {name: [] for name, _ in STRATEGIES}
    strategy_ndcgs = {name: [] for name, _ in STRATEGIES}

    for qi, case in enumerate(GROUND_TRUTH, start=1):
        query = case["query"]
        profile = case["profile"]
        relevant = set(case["relevant"])
        label = query if query else f"(profile-only) {profile}"

        for strat_name, strat_fn in STRATEGIES:
            retrieved = strat_fn(query, profile)
            p = precision(retrieved, relevant)
            r = recall(retrieved, relevant)
            f1 = f1_score(p, r)
            p_at_5 = precision(retrieved[:5], relevant)
            ap = average_precision(retrieved, relevant)
            ndcg = ndcg_at_k(retrieved, relevant, k=TOP_N)

            strategy_aps[strat_name].append(ap)
            strategy_ndcgs[strat_name].append(ndcg)

            per_query_rows.append({
                "qi": qi,
                "label": label,
                "strategy": strat_name,
                "precision": p,
                "recall": r,
                "f1": f1,
                "p_at_5": p_at_5,
                "ap": ap,
                "ndcg": ndcg,
                "retrieved": retrieved,
            })

    return per_query_rows, strategy_aps, strategy_ndcgs


def build_report(per_query_rows, strategy_aps, strategy_ndcgs):
    lines = []
    lines.append("=" * 78)
    lines.append("ScholarSearch IR Evaluation")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"Ground truth test set: {len(GROUND_TRUTH)} queries")
    lines.append(f"Strategies: {', '.join(name for name, _ in STRATEGIES)}")
    lines.append(f"Top-N retrieved per query: {TOP_N}")
    lines.append("")

    # ---- Summary table: MAP and average NDCG@10 per strategy ----
    lines.append("-" * 78)
    lines.append("SUMMARY: MAP and Average NDCG@10 by Strategy")
    lines.append("-" * 78)
    header = f"{'Strategy':<20}{'MAP':>12}{'Avg NDCG@10':>16}"
    lines.append(header)
    lines.append("-" * len(header))
    for strat_name, _ in STRATEGIES:
        aps = strategy_aps[strat_name]
        ndcgs = strategy_ndcgs[strat_name]
        map_score = sum(aps) / len(aps) if aps else 0.0
        avg_ndcg = sum(ndcgs) / len(ndcgs) if ndcgs else 0.0
        lines.append(f"{strat_name:<20}{map_score:>12.4f}{avg_ndcg:>16.4f}")
    lines.append("")

    # ---- Per-query breakdown ----
    lines.append("-" * 78)
    lines.append("PER-QUERY BREAKDOWN")
    lines.append("-" * 78)

    for case_idx in range(1, len(GROUND_TRUTH) + 1):
        rows = [r for r in per_query_rows if r["qi"] == case_idx]
        label = rows[0]["label"]
        lines.append("")
        lines.append(f"Query {case_idx}: {label!r}")
        col_header = (
            f"  {'Strategy':<20}{'Prec':>8}{'Rec':>8}{'F1':>8}"
            f"{'P@5':>8}{'AP':>8}{'NDCG@10':>10}"
        )
        lines.append(col_header)
        lines.append("  " + "-" * (len(col_header) - 2))
        for r in rows:
            lines.append(
                f"  {r['strategy']:<20}{r['precision']:>8.3f}{r['recall']:>8.3f}"
                f"{r['f1']:>8.3f}{r['p_at_5']:>8.3f}{r['ap']:>8.3f}{r['ndcg']:>10.3f}"
            )

    lines.append("")
    lines.append("=" * 78)
    return "\n".join(lines)


def main():
    per_query_rows, strategy_aps, strategy_ndcgs = evaluate()
    report = build_report(per_query_rows, strategy_aps, strategy_ndcgs)
    print(report)

    out_path = "evaluation_results.txt"
    with open(out_path, "w") as f:
        f.write(report + "\n")
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
