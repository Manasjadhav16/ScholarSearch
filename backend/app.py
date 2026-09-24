"""
ScholarSearch API
-------------------
Flask backend for a hybrid scholarship/scheme retrieval engine.

Core IR contribution (write this up in the report's Methodology section):
  Most scholarship search tools are either (a) a static filtered list, or
  (b) plain keyword search with no notion of whether the user actually
  qualifies. This engine combines the two:

    hybrid_score = alpha * text_relevance(query, scheme)
                 + (1 - alpha) * eligibility_match(profile, scheme)

  - text_relevance comes from SQLite FTS5's BM25 ranking over the scheme's
    name/provider/level/category/description/tags fields, after a domain
    specific query-expansion pass (see expand_query()).
  - eligibility_match is a structured 0-1 score built from how well the
    user's stated category/gender/state/income/marks line up with the
    scheme's stated eligibility fields (see eligibility_match()).
  - alpha defaults to 0.5 (balanced) but shifts toward eligibility when a
    full profile is supplied and toward text when only a free-text query
    is given with no profile.

This lets "I'm an OBC engineering student from Maharashtra, family income
around 2 lakh" outrank a scheme that merely mentions those words but that
the user doesn't actually qualify for.
"""

import sqlite3
import os
import re
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "scholarsearch.db")

# ---------------- DB HELPERS ----------------


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- QUERY PREPROCESSING / EXPANSION ----------------

# Domain-specific synonym map so plain-language queries reach the right
# scheme categories even when the user doesn't know the official terms.
CATEGORY_SYNONYMS = {
    "dalit": ["SC", "scheduled caste"],
    "adivasi": ["ST", "scheduled tribe", "tribal"],
    "backward": ["OBC", "backward class"],
    "obc": ["backward class", "other backward"],
    "minority": ["muslim", "christian", "sikh", "buddhist", "parsi", "jain"],
    "disabled": ["PWD", "specially abled", "disability"],
    "differently": ["PWD", "disability", "specially abled"],
    "poor": ["EWS", "economically weaker", "low income"],
    "girl": ["women", "female", "girls"],
    "abroad": ["overseas", "study abroad", "foreign university"],
    "masters": ["postgraduate", "PG", "MS", "M.Tech"],
    "phd": ["doctoral", "fellowship", "research"],
    "engineering": ["technical", "AICTE", "diploma"],
}


def preprocess_query(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split()).lower()


def expand_query(text: str) -> str:
    words = preprocess_query(text).split()
    expanded = set(words)
    for w in words:
        if w in CATEGORY_SYNONYMS:
            for syn in CATEGORY_SYNONYMS[w]:
                for token in syn.lower().split():
                    token = re.sub(r"[^a-z0-9]", "", token)
                    if token:
                        expanded.add(token)
    # FTS5 MATCH with OR across all (original + expanded) terms
    return " OR ".join(sorted(expanded)) if expanded else ""


# ---------------- ELIGIBILITY MATCH SCORING ----------------

def eligibility_match(profile: dict, scheme: sqlite3.Row) -> float:
    """
    Returns a 0-1 score for how well `profile` fits `scheme`'s stated
    eligibility. Gender and category are hard disqualifiers: a scheme
    explicitly restricted to a different gender or category than the
    profile's scores 0.0 outright, short-circuiting the rest of the
    scoring. State/income/percentage/level remain soft, partial-credit
    criteria weighted equally among themselves; criteria the user didn't
    specify, or the scheme doesn't restrict, are skipped (neither help nor
    hurt the score).
    """
    # Gender: hard disqualifier. A scheme restricted to a gender other than
    # the profile's gender is not eligible at all, regardless of how well
    # other criteria line up.
    if profile.get("gender"):
        s_gender = (scheme["gender"] or "any").lower()
        if s_gender != "any" and s_gender != profile["gender"].lower():
            return 0.0

    # Category: hard disqualifier. Scheme category "General"/"Any"/empty is
    # open to everyone; otherwise the profile's category must overlap with
    # one of the scheme's eligible categories (some schemes list multiple,
    # separated by "/" or ",").
    if profile.get("category"):
        s_cat_raw = (scheme["category"] or "").lower()
        s_cats = [c.strip() for c in re.split(r"[/,]", s_cat_raw) if c.strip()]
        p_cat = profile["category"].lower()
        if s_cat_raw not in ("general", "any", "") and p_cat not in s_cats:
            return 0.0

    points = 0.0
    max_points = 0.0

    # State (All India schemes match everyone)
    if profile.get("state"):
        max_points += 1
        s_state = (scheme["state"] or "").lower()
        if s_state in ("all india", "") or s_state == profile["state"].lower():
            points += 1

    # Income ceiling
    if profile.get("income") is not None:
        max_points += 1
        cap = scheme["max_income"]
        if cap is None or profile["income"] <= cap:
            points += 1

    # Minimum percentage required
    if profile.get("percentage") is not None:
        max_points += 1
        req = scheme["min_percentage"]
        if req is None or profile["percentage"] >= req:
            points += 1

    # Education level (loose substring match since level fields are free text
    # like "UG/PG" or "Study Abroad (Masters)")
    if profile.get("level"):
        max_points += 1
        s_level = (scheme["level"] or "").lower()
        if profile["level"].lower() in s_level:
            points += 1

    if max_points == 0:
        return 0.5  # no profile info to judge against -> neutral
    return points / max_points


def normalize_bm25(rank: float, all_ranks: list) -> float:
    """FTS5 bm25() rank is negative, more negative = more relevant.
    Min-max normalize the batch of ranks to a 0-1 scale (1 = most relevant)."""
    if not all_ranks:
        return 0.0
    lo, hi = min(all_ranks), max(all_ranks)
    if hi == lo:
        return 1.0
    # rank is negative-better; flip and normalize
    return (hi - rank) / (hi - lo)


# ---------------- ROUTES ----------------


@app.route("/api/search", methods=["POST"])
def search():
    data = request.get_json(force=True) or {}
    query = (data.get("query") or "").strip()
    profile = data.get("profile") or {}

    db = get_db()
    cur = db.cursor()

    if query:
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
            # fall back to LIKE search if FTS finds nothing
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
    else:
        cur.execute("SELECT *, 0.0 as rank FROM schemes")
        rows = cur.fetchall()

    all_ranks = [r["rank"] for r in rows]
    has_profile = bool(profile)
    alpha = 0.35 if has_profile else 1.0  # weight text vs eligibility

    results = []
    for r in rows:
        text_score = normalize_bm25(r["rank"], all_ranks) if query else 0.5
        elig_score = eligibility_match(profile, r) if has_profile else 0.5
        if has_profile and elig_score == 0.0:
            # eligibility_match() hit a hard disqualifier (wrong gender/
            # category) -- the scheme is flatly ineligible, so it always
            # shows 0% match regardless of text relevance.
            hybrid = 0.0
        else:
            hybrid = alpha * text_score + (1 - alpha) * elig_score
        row_dict = dict(r)
        row_dict.pop("rank", None)
        row_dict["text_score"] = round(text_score, 3)
        row_dict["eligibility_score"] = round(elig_score, 3)
        row_dict["match_score"] = round(hybrid, 3)
        results.append(row_dict)

    results.sort(key=lambda x: x["match_score"], reverse=True)
    db.close()

    return jsonify({
        "success": True,
        "count": len(results),
        "query": query,
        "profile_applied": has_profile,
        "alpha": alpha,
        "results": results,
    })


@app.route("/api/schemes", methods=["GET"])
def list_schemes():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    offset = (page - 1) * per_page

    db = get_db()
    cur = db.cursor()
    total = cur.execute("SELECT COUNT(*) FROM schemes").fetchone()[0]
    cur.execute("SELECT * FROM schemes ORDER BY name LIMIT ? OFFSET ?", (per_page, offset))
    rows = [dict(r) for r in cur.fetchall()]
    db.close()

    return jsonify({
        "success": True, "page": page, "per_page": per_page,
        "total": total, "results": rows,
    })


@app.route("/api/schemes/<int:scheme_id>", methods=["GET"])
def get_scheme(scheme_id):
    db = get_db()
    cur = db.cursor()
    row = cur.execute("SELECT * FROM schemes WHERE scheme_id = ?", (scheme_id,)).fetchone()
    db.close()
    if row is None:
        return jsonify({"error": "Scheme not found"}), 404
    return jsonify({"success": True, "result": dict(row)})


@app.route("/api/filters", methods=["GET"])
def get_filters():
    """Distinct values to populate frontend dropdowns."""
    db = get_db()
    cur = db.cursor()
    categories = [r[0] for r in cur.execute("SELECT DISTINCT category FROM schemes ORDER BY category")]
    states = [r[0] for r in cur.execute("SELECT DISTINCT state FROM schemes ORDER BY state")]
    levels = [r[0] for r in cur.execute("SELECT DISTINCT level FROM schemes ORDER BY level")]
    db.close()
    return jsonify({"categories": categories, "states": states, "levels": levels})


@app.route("/api/stats", methods=["GET"])
def stats():
    db = get_db()
    cur = db.cursor()
    total = cur.execute("SELECT COUNT(*) FROM schemes").fetchone()[0]
    by_category = [dict(r) for r in cur.execute(
        "SELECT category, COUNT(*) as count FROM schemes GROUP BY category ORDER BY count DESC")]
    by_level = [dict(r) for r in cur.execute(
        "SELECT level, COUNT(*) as count FROM schemes GROUP BY level ORDER BY count DESC")]
    by_state = [dict(r) for r in cur.execute(
        "SELECT state, COUNT(*) as count FROM schemes GROUP BY state ORDER BY count DESC")]
    db.close()
    return jsonify({
        "success": True,
        "stats": {
            "total_schemes": total,
            "by_category": by_category,
            "by_level": by_level,
            "by_state": by_state,
        }
    })


@app.route("/api/health", methods=["GET"])
def health():
    try:
        db = get_db()
        total = db.execute("SELECT COUNT(*) FROM schemes").fetchone()[0]
        db.close()
        return jsonify({"status": "healthy", "total_schemes": total, "fts_enabled": True})
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print("Database not found. Run `python3 seed_data.py` first.")
    app.run(debug=True, host="0.0.0.0", port=5001)
