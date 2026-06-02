import sqlite3
import json
import random
import string
from datetime import datetime
from typing import Optional

DB_PATH = "golf_scores.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS rounds (
            id TEXT PRIMARY KEY,
            course TEXT NOT NULL,
            format TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT NOT NULL,
            team_name TEXT NOT NULL,
            p1_name TEXT NOT NULL,
            p1_handicap INTEGER NOT NULL,
            p1_gender TEXT NOT NULL DEFAULT 'mens',
            p2_name TEXT NOT NULL,
            p2_handicap INTEGER NOT NULL,
            p2_gender TEXT NOT NULL DEFAULT 'mens',
            FOREIGN KEY (round_id) REFERENCES rounds(id)
        );

        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT NOT NULL,
            team_id INTEGER NOT NULL,
            player_num INTEGER NOT NULL,
            hole INTEGER NOT NULL,
            gross INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(round_id, team_id, player_num, hole),
            FOREIGN KEY (round_id) REFERENCES rounds(id),
            FOREIGN KEY (team_id) REFERENCES teams(id)
        );
    """)
    conn.commit()
    conn.close()


def _make_round_id() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def create_round(course: str, fmt: str) -> str:
    conn = get_conn()
    while True:
        rid = _make_round_id()
        try:
            conn.execute(
                "INSERT INTO rounds (id, course, format, created_at) VALUES (?,?,?,?)",
                (rid, course, fmt, datetime.utcnow().isoformat()),
            )
            conn.commit()
            break
        except sqlite3.IntegrityError:
            continue
    conn.close()
    return rid


def round_exists(rid: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM rounds WHERE id=?", (rid,)).fetchone()
    conn.close()
    return row is not None


def get_round(rid: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM rounds WHERE id=?", (rid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_team(round_id, team_name, p1_name, p1_hcp, p1_gender, p2_name, p2_hcp, p2_gender) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO teams (round_id,team_name,p1_name,p1_handicap,p1_gender,p2_name,p2_handicap,p2_gender)
           VALUES (?,?,?,?,?,?,?,?)""",
        (round_id, team_name, p1_name, p1_hcp, p1_gender, p2_name, p2_hcp, p2_gender),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def get_teams(round_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM teams WHERE round_id=? ORDER BY id", (round_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_score(round_id: str, team_id: int, player_num: int, hole: int, gross: int):
    conn = get_conn()
    conn.execute(
        """INSERT INTO scores (round_id,team_id,player_num,hole,gross,updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(round_id,team_id,player_num,hole)
           DO UPDATE SET gross=excluded.gross, updated_at=excluded.updated_at""",
        (round_id, team_id, player_num, hole, gross, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_scores(round_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM scores WHERE round_id=? ORDER BY team_id, player_num, hole",
        (round_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_active_rounds() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM rounds WHERE status='active' ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
