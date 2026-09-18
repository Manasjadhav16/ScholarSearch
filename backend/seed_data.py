"""
seed_data.py
-------------
Builds scholarsearch.db (SQLite) from schemes_data.py, creates the schemes
table, an FTS5 virtual table for full-text search, and keeps them in sync
via triggers. Run this once before starting the Flask app:

    python3 seed_data.py
"""

import sqlite3
import os
from schemes_data import SCHEMES

DB_PATH = os.path.join(os.path.dirname(__file__), "scholarsearch.db")


def build_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE schemes (
            scheme_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider TEXT,
            level TEXT,
            category TEXT,
            gender TEXT,
            state TEXT,
            max_income INTEGER,
            min_percentage INTEGER,
            benefit_amount TEXT,
            description TEXT,
            tags TEXT,
            url TEXT
        )
    """)

    cur.execute("""
        CREATE VIRTUAL TABLE schemes_fts USING fts5(
            name, provider, level, category, description, tags,
            content='schemes',
            content_rowid='scheme_id'
        )
    """)

    # Keep FTS in sync with the base table
    cur.executescript("""
        CREATE TRIGGER schemes_ai AFTER INSERT ON schemes BEGIN
            INSERT INTO schemes_fts(rowid, name, provider, level, category, description, tags)
            VALUES (new.scheme_id, new.name, new.provider, new.level, new.category, new.description, new.tags);
        END;
        CREATE TRIGGER schemes_ad AFTER DELETE ON schemes BEGIN
            DELETE FROM schemes_fts WHERE rowid = old.scheme_id;
        END;
        CREATE TRIGGER schemes_au AFTER UPDATE ON schemes BEGIN
            DELETE FROM schemes_fts WHERE rowid = old.scheme_id;
            INSERT INTO schemes_fts(rowid, name, provider, level, category, description, tags)
            VALUES (new.scheme_id, new.name, new.provider, new.level, new.category, new.description, new.tags);
        END;
    """)

    for s in SCHEMES:
        cur.execute("""
            INSERT INTO schemes
            (name, provider, level, category, gender, state, max_income,
             min_percentage, benefit_amount, description, tags, url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            s["name"], s["provider"], s["level"], s["category"], s["gender"],
            s["state"], s["max_income"], s["min_percentage"],
            s["benefit_amount"], s["description"], s["tags"], s["url"],
        ))

    cur.execute("CREATE INDEX idx_category ON schemes(category)")
    cur.execute("CREATE INDEX idx_state ON schemes(state)")
    cur.execute("CREATE INDEX idx_level ON schemes(level)")

    conn.commit()
    count = cur.execute("SELECT COUNT(*) FROM schemes").fetchone()[0]
    conn.close()
    print(f"Database built: {DB_PATH}")
    print(f"Loaded {count} schemes with FTS5 index.")


if __name__ == "__main__":
    build_database()
