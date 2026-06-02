import sqlite3
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
            id          TEXT PRIMARY KEY,
            course      TEXT NOT NULL,
            format      TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS teams (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id        TEXT NOT NULL,
            team_name       TEXT NOT NULL,
            p1_name         TEXT NOT NULL,
            p1_handicap     REAL NOT NULL,
            p1_tee          TEXT NOT NULL DEFAULT 'Blue',
            p2_name         TEXT NOT NULL,
            p2_handicap     REAL NOT NULL,
            p2_tee          TEXT NOT NULL DEFAULT 'Blue',
            pin             TEXT NOT NULL DEFAULT '0000',
            FOREIGN KEY (round_id) REFERENCES rounds(id)
        );

        CREATE TABLE IF NOT EXISTS scores (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id    TEXT NOT NULL,
            team_id     INTEGER NOT NULL,
            player_num  INTEGER NOT NULL,
            hole        INTEGER NOT NULL,
            gross       INTEGER,
            updated_at  TEXT NOT NULL,
            UNIQUE(round_id, team_id, player_num, hole),
            FOREIGN KEY (round_id) REFERENCES rounds(id),
            FOREIGN KEY (team_id)  REFERENCES teams(id)
        );
    """)

    # Migrations — add new columns to old DBs gracefully
    for sql in [
        "ALTER TABLE teams ADD COLUMN p1_tee TEXT NOT NULL DEFAULT 'Blue'",
        "ALTER TABLE teams ADD COLUMN p2_tee TEXT NOT NULL DEFAULT 'Blue'",
        "ALTER TABLE teams ADD COLUMN pin TEXT NOT NULL DEFAULT '0000'",
    ]:
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass

    # Wolf tables
    c.executescript("""
        CREATE TABLE IF NOT EXISTS wolf_players (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id    TEXT NOT NULL,
            wolf_order  INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            handicap    REAL NOT NULL,
            tee         TEXT NOT NULL DEFAULT 'Blue',
            FOREIGN KEY (round_id) REFERENCES rounds(id)
        );
        CREATE TABLE IF NOT EXISTS wolf_scores (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id    TEXT NOT NULL,
            player_id   INTEGER NOT NULL,
            hole        INTEGER NOT NULL,
            gross       INTEGER,
            updated_at  TEXT NOT NULL,
            UNIQUE(round_id, player_id, hole),
            FOREIGN KEY (player_id) REFERENCES wolf_players(id)
        );
        CREATE TABLE IF NOT EXISTS wolf_decisions (
            round_id    TEXT NOT NULL,
            hole        INTEGER NOT NULL,
            decision    TEXT NOT NULL,
            partner_id  INTEGER,
            PRIMARY KEY (round_id, hole)
        );
    """)

    conn.commit()
    conn.close()


# ── Wolf DB functions ─────────────────────────────────────────────────────────

def add_wolf_player(round_id: str, wolf_order: int, player_name: str,
                    handicap: float, tee: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO wolf_players (round_id,wolf_order,player_name,handicap,tee) VALUES (?,?,?,?,?)",
        (round_id, wolf_order, player_name, handicap, tee),
    )
    conn.commit(); tid = cur.lastrowid; conn.close()
    return tid


def get_wolf_players(round_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM wolf_players WHERE round_id=? ORDER BY wolf_order", (round_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_wolf_players(round_id: str):
    conn = get_conn()
    for tbl in ("wolf_decisions", "wolf_scores", "wolf_players"):
        conn.execute(f"DELETE FROM {tbl} WHERE round_id=?", (round_id,))
    conn.commit(); conn.close()


def upsert_wolf_score(round_id: str, player_id: int, hole: int, gross: Optional[int]):
    conn = get_conn()
    if gross is None:
        conn.execute("DELETE FROM wolf_scores WHERE round_id=? AND player_id=? AND hole=?",
                     (round_id, player_id, hole))
    else:
        conn.execute(
            """INSERT INTO wolf_scores (round_id,player_id,hole,gross,updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(round_id,player_id,hole)
               DO UPDATE SET gross=excluded.gross, updated_at=excluded.updated_at""",
            (round_id, player_id, hole, gross, datetime.utcnow().isoformat()),
        )
    conn.commit(); conn.close()


def get_wolf_scores(round_id: str) -> dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT player_id, hole, gross FROM wolf_scores WHERE round_id=?", (round_id,)
    ).fetchall()
    conn.close()
    return {(r["player_id"], r["hole"]): r["gross"] for r in rows}


def set_wolf_decision(round_id: str, hole: int, decision: str, partner_id: Optional[int] = None):
    conn = get_conn()
    conn.execute(
        """INSERT INTO wolf_decisions (round_id,hole,decision,partner_id) VALUES (?,?,?,?)
           ON CONFLICT(round_id,hole)
           DO UPDATE SET decision=excluded.decision, partner_id=excluded.partner_id""",
        (round_id, hole, decision, partner_id),
    )
    conn.commit(); conn.close()


def clear_wolf_decision(round_id: str, hole: int):
    conn = get_conn()
    conn.execute("DELETE FROM wolf_decisions WHERE round_id=? AND hole=?", (round_id, hole))
    conn.commit(); conn.close()


def get_wolf_decisions(round_id: str) -> dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT hole, decision, partner_id FROM wolf_decisions WHERE round_id=?", (round_id,)
    ).fetchall()
    conn.close()
    return {r["hole"]: {"decision": r["decision"], "partner_id": r["partner_id"]} for r in rows}


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


def finalize_round(rid: str):
    conn = get_conn()
    conn.execute("UPDATE rounds SET status='completed' WHERE id=?", (rid,))
    conn.commit()
    conn.close()


def add_team(round_id, team_name, p1_name, p1_hcp, p1_tee, p2_name, p2_hcp, p2_tee) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO teams
           (round_id, team_name, p1_name, p1_handicap, p1_tee, p2_name, p2_handicap, p2_tee, pin)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (round_id, team_name, p1_name, p1_hcp, p1_tee, p2_name, p2_hcp, p2_tee, team_name),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def get_teams(round_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM teams WHERE round_id=? ORDER BY id", (round_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_score(round_id: str, team_id: int, player_num: int, hole: int, gross: Optional[int]):
    conn = get_conn()
    if gross is None:
        # Remove score (player picked up)
        conn.execute(
            "DELETE FROM scores WHERE round_id=? AND team_id=? AND player_num=? AND hole=?",
            (round_id, team_id, player_num, hole),
        )
    else:
        conn.execute(
            """INSERT INTO scores (round_id, team_id, player_num, hole, gross, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(round_id, team_id, player_num, hole)
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


def list_completed_rounds() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM rounds WHERE status='completed' ORDER BY created_at DESC LIMIT 30"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
