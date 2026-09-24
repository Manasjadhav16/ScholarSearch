"""
show_ir_concepts.py
--------------------
Standalone demonstration script for the IR mini-project report. NOT used by
the Flask app (app.py) — this exists purely to make two IR concepts explicit
and verifiable outside the running system:

  Part 1 (Experiment 2): Text Preprocessing
      Tokenization -> Stop Word Removal -> Noun Group Identification
      -> Lemmatization, applied to one sample scheme description.

  Part 2 (Experiment 7): Indexing (Inverted Index)
      A hand-rolled inverted index built from scratch over all 45 scheme
      descriptions, cross-checked term-by-term against SQLite FTS5's own
      inverted index (schemes_fts) to prove FTS5 is really doing the same
      job as a textbook inverted index.

Run with:  python3 show_ir_concepts.py
Output is printed to the console AND written to
backend/ir_concepts_demo_output.txt.
"""

import os
import re
import sqlite3

# macOS framework builds of Python often ship without a usable local CA
# bundle, which makes nltk.download() fail with CERTIFICATE_VERIFY_FAILED.
# Point OpenSSL at certifi's bundle (if installed) before any SSL connection
# is made, so downloads work without disabling verification.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

import nltk

from schemes_data import SCHEMES

# ---------------- NLTK RESOURCE SETUP ----------------
# Download quietly; don't fail the script if a particular resource name
# isn't available on this nltk version (tagger package names changed
# between nltk releases, hence trying both variants).

for resource in ("punkt", "punkt_tab", "stopwords", "wordnet"):
    try:
        nltk.download(resource, quiet=True)
    except Exception:
        pass

for tagger in ("averaged_perceptron_tagger", "averaged_perceptron_tagger_eng"):
    try:
        nltk.download(tagger, quiet=True)
    except Exception:
        pass

from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

DB_PATH = os.path.join(os.path.dirname(__file__), "scholarsearch.db")
SEED_SCRIPT = os.path.join(os.path.dirname(__file__), "seed_data.py")

# ---------------- PRINT + LOG HELPER ----------------

LOG = []


def out(line=""):
    """Print a line to the console and also record it for the log file."""
    print(line)
    LOG.append(str(line))


# ==========================================================================
# PART 1 -- EXPERIMENT 2: TEXT PREPROCESSING
# ==========================================================================


def run_preprocessing_demo():
    out("=" * 78)
    out("EXPERIMENT 2: TEXT PREPROCESSING")
    out("=" * 78)

    scheme = next(s for s in SCHEMES if s["name"] == "AICTE Pragati Scholarship for Girls")
    document = scheme["description"]

    out("")
    out(f"Sample scheme: {scheme['name']}")
    out("Sample input document (description field):")
    out(f"  {document}")

    # ---- Step 1: Tokenization ----
    out("")
    out("-" * 78)
    out("Step 1: Tokenization (nltk.word_tokenize, lowercase, alphabetic only)")
    out("-" * 78)
    raw_tokens = word_tokenize(document)
    tokens = [t.lower() for t in raw_tokens if t.isalpha()]
    out(f"Tokens ({len(tokens)}):")
    out(f"  {tokens}")

    # ---- Step 2: Stop Word Removal ----
    out("")
    out("-" * 78)
    out("Step 2: Stop Word Removal (NLTK English stopwords)")
    out("-" * 78)
    stop_words = set(stopwords.words("english"))
    filtered_tokens = [t for t in tokens if t not in stop_words]
    out(f"Tokens after stop word removal ({len(filtered_tokens)}):")
    out(f"  {filtered_tokens}")

    # ---- Step 3: Noun Group Identification ----
    out("")
    out("-" * 78)
    out("Step 3: Noun Group Identification (POS-tag, group consecutive NN/NNS/NNP/NNPS)")
    out("-" * 78)
    tagged = nltk.pos_tag(filtered_tokens)
    out(f"POS tags: {tagged}")

    noun_tags = {"NN", "NNS", "NNP", "NNPS"}
    noun_groups = []
    current_group = []
    for word, tag in tagged:
        if tag in noun_tags:
            current_group.append(word)
        else:
            if current_group:
                noun_groups.append(" ".join(current_group))
                current_group = []
    if current_group:
        noun_groups.append(" ".join(current_group))

    out(f"Noun groups identified ({len(noun_groups)}):")
    out(f"  {noun_groups}")

    # ---- Step 4: Lemmatization ----
    out("")
    out("-" * 78)
    out("Step 4: Lemmatization (WordNetLemmatizer, default noun mode)")
    out("-" * 78)
    lemmatizer = WordNetLemmatizer()
    lemmas = [lemmatizer.lemmatize(t) for t in filtered_tokens]
    changed = [(orig, lem) for orig, lem in zip(filtered_tokens, lemmas) if orig != lem]
    out("Tokens whose form changed after lemmatization (before -> after):")
    if changed:
        for orig, lem in changed:
            out(f"  {orig} -> {lem}")
    else:
        out("  (none)")


# ==========================================================================
# PART 2 -- EXPERIMENT 7: INDEXING (INVERTED INDEX)
# ==========================================================================


def build_inverted_index():
    """Hand-rolled inverted index: term -> sorted list of 0-based SCHEMES
    indices whose description contains that term.

    Tokenization here uses a plain regex word-splitter (letters/digits runs,
    lowercased) rather than nltk.word_tokenize. This matters for compound
    words like "loan-scholarship": SQLite FTS5's default 'unicode61'
    tokenizer (used by schemes_fts, see seed_data.py) treats '-' as a
    separator and indexes "loan" and "scholarship" as two tokens, whereas
    nltk.word_tokenize keeps "loan-scholarship" as one hyphenated token,
    which would then get dropped by an alphabetic-only filter. Splitting on
    non-alphanumeric characters here mirrors FTS5's own tokenizer so the two
    indexes are built the same way and are directly comparable term-by-term.
    """
    index = {}
    for idx, scheme in enumerate(SCHEMES):
        tokens = set(re.findall(r"[a-z0-9]+", scheme["description"].lower()))
        for term in tokens:
            index.setdefault(term, []).append(idx)
    for term in index:
        index[term].sort()
    return index


def run_indexing_demo():
    out("")
    out("=" * 78)
    out("EXPERIMENT 7: INDEXING (INVERTED INDEX)")
    out("=" * 78)

    out("")
    out(f"Building a hand-rolled inverted index over all {len(SCHEMES)} scheme descriptions...")
    index = build_inverted_index()
    out(f"Vocabulary size (unique terms): {len(index)}")

    example_terms = ["scholarship", "girls", "abroad"]

    out("")
    out("-" * 78)
    out("Hand-built posting lists (0-based SCHEMES indices)")
    out("-" * 78)
    for term in example_terms:
        postings = index.get(term, [])
        out(f"  '{term}': {postings}")

    # ---- Cross-check against SQLite FTS5's real inverted index ----
    if not os.path.exists(DB_PATH):
        out("")
        out(f"scholarsearch.db not found at {DB_PATH} -- running seed_data.py to build it...")
        import subprocess
        subprocess.run(["python3", SEED_SCRIPT], check=True, cwd=os.path.dirname(__file__))

    out("")
    out("-" * 78)
    out("SQLite FTS5 posting lists (SELECT rowid FROM schemes_fts WHERE schemes_fts MATCH ?)")
    out("-" * 78)
    out("")
    out("Note: schemes_fts is a multi-column FTS5 index (name, provider, level,")
    out("category, description, tags -- see seed_data.py), while our hand-built")
    out("index above covers only the description field. To compare like with")
    out("like, the FTS5 query below is restricted to the description column via")
    out("FTS5's 'description:term' column-filter syntax, so both indexes are")
    out("built over the exact same text.")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    all_match = True
    for term in example_terms:
        cur.execute("SELECT rowid FROM schemes_fts WHERE schemes_fts MATCH ?", (f"description:{term}",))
        fts_rowids = sorted(r[0] for r in cur.fetchall())
        out(f"  '{term}': {fts_rowids}")

        # Convert hand-built 0-based SCHEMES indices to 1-based scheme_ids
        # (scheme_id is AUTOINCREMENT starting at 1, SCHEMES inserted in order).
        hand_built_ids = {i + 1 for i in index.get(term, [])}
        fts_ids = set(fts_rowids)

        verdict = "MATCH" if hand_built_ids == fts_ids else "MISMATCH"
        if verdict == "MISMATCH":
            all_match = False

        out("")
        out(f"  Term: '{term}'")
        out(f"    Hand-built index (as 1-based scheme_ids): {sorted(hand_built_ids)}")
        out(f"    FTS5 query result (rowid = scheme_id):     {sorted(fts_ids)}")
        out(f"    Verdict: {verdict}")
        out("")

    conn.close()

    out("-" * 78)
    if all_match:
        out("RESULT: All three terms MATCH -- SQLite FTS5's schemes_fts table is")
        out("functioning as a real inverted index, confirmed against a hand-built")
        out("inverted index built independently from the same data.")
    else:
        out("RESULT: At least one term MISMATCHED -- see details above.")
    out("-" * 78)

    return all_match


def main():
    run_preprocessing_demo()
    all_match = run_indexing_demo()

    out_path = os.path.join(os.path.dirname(__file__), "ir_concepts_demo_output.txt")
    with open(out_path, "w") as f:
        f.write("\n".join(LOG) + "\n")
    out("")
    out(f"Full output written to {out_path}")

    return all_match


if __name__ == "__main__":
    main()
