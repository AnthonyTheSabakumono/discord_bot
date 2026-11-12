import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("BOT_DB_PATH") or os.path.join(BASE_DIR, "data", "bot.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

SCHEMA_VERSION = 2

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode = WAL")
conn.execute("PRAGMA foreign_keys = ON")


# ----------------------
# Schema
# ----------------------
def _drop_old_cohort_tables():
    """v1-д cohort хүснэгтүүд хоосон байсан. Өгөгдөлтэй бол устгахгүй."""
    tables = ("progress", "submissions", "enrollments", "cohorts")
    for t in tables:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (t,)
        ).fetchone()
        if exists and conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]:
            raise RuntimeError(f"{t} хүснэгтэд өгөгдөл байна, автоматаар устгахгүй")
    conn.executescript("".join(f"DROP TABLE IF EXISTS {t};" for t in tables))


def _add_missing_columns():
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    for name, ddl in (("anonymous", "INTEGER NOT NULL DEFAULT 0"), ("avatar_url", "TEXT")):
        if name not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
    conn.commit()


def init_db():
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    if version < 2:
        _drop_old_cohort_tables()
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    _add_missing_columns()
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


# ----------------------
# Users
# ----------------------
USER_FIELDS = {
    "display_name", "avatar_url", "checkin_streak", "last_checkin",
    "quiz_date", "quiz_count", "recent_quiz", "anonymous",
}


def ensure_user(user_id, display_name=None, avatar_url=None):
    uid = str(user_id)
    with conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
        if display_name:
            conn.execute("UPDATE users SET display_name = ? WHERE user_id = ?", (display_name, uid))
        if avatar_url:
            conn.execute("UPDATE users SET avatar_url = ? WHERE user_id = ?", (avatar_url, uid))
    return get_user(uid)


def get_user(user_id):
    return conn.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),)).fetchone()


def update_user(user_id, **fields):
    bad = set(fields) - USER_FIELDS
    if bad:
        raise ValueError(f"Зөвшөөрөгдөөгүй талбар: {bad}")
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE users SET {cols} WHERE user_id = ?", (*fields.values(), str(user_id)))


# ----------------------
# EXP
# ----------------------
def level_of(exp):
    return exp // 100 + 1


def total_exp(user_id, cohort_id=None):
    if cohort_id is None:
        sql = "SELECT COALESCE(SUM(amount), 0) FROM exp_events WHERE user_id = ? AND cohort_id IS NULL"
        args = (str(user_id),)
    else:
        sql = "SELECT COALESCE(SUM(amount), 0) FROM exp_events WHERE user_id = ? AND cohort_id = ?"
        args = (str(user_id), cohort_id)
    return conn.execute(sql, args).fetchone()[0]


def add_exp(user_id, source, amount, cohort_id=None):
    """EXP нэмнэ. Main board дээр level ахивал True буцаана."""
    ensure_user(user_id)
    before = total_exp(user_id)
    with conn:
        conn.execute(
            "INSERT INTO exp_events (user_id, source, amount, cohort_id) VALUES (?, ?, ?, ?)",
            (str(user_id), source, amount, cohort_id),
        )
    return cohort_id is None and level_of(before + amount) > level_of(before)


def leaderboard(limit=10, cohort_id=None):
    if cohort_id is None:
        sql = ("SELECT user_id, SUM(amount) AS exp FROM exp_events WHERE cohort_id IS NULL "
               "GROUP BY user_id ORDER BY exp DESC LIMIT ?")
        args = (limit,)
    else:
        sql = ("SELECT user_id, SUM(amount) AS exp FROM exp_events WHERE cohort_id = ? "
               "GROUP BY user_id ORDER BY exp DESC LIMIT ?")
        args = (cohort_id, limit)
    return conn.execute(sql, args).fetchall()


# ----------------------
# Bot state (суваг, role, pinned message ID гэх мэт)
# ----------------------
def state_get(key, default=None):
    row = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def state_set(key, value):
    with conn:
        conn.execute(
            "INSERT INTO bot_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


# ----------------------
# Cohorts
# ----------------------
def active_cohort():
    """Хаагдаагүй хамгийн сүүлийн cohort."""
    return conn.execute(
        "SELECT * FROM cohorts WHERE status IN ('scheduled', 'running', 'finished') "
        "ORDER BY start_date DESC LIMIT 1"
    ).fetchone()


def create_cohort(cohort_id, name, program_id, start_date, days, min_seats, max_seats, join_cutoff_day):
    if active_cohort():
        raise ValueError("Хаагдаагүй cohort байна")
    if conn.execute("SELECT 1 FROM cohorts WHERE cohort_id = ?", (cohort_id,)).fetchone():
        raise ValueError("Ийм ID-тай cohort байна")
    with conn:
        conn.execute(
            "INSERT INTO cohorts (cohort_id, name, program_id, start_date, days, min_seats, max_seats, join_cutoff_day) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cohort_id, name, program_id, start_date, days, min_seats, max_seats, join_cutoff_day),
        )


def set_cohort_status(cohort_id, status):
    with conn:
        conn.execute("UPDATE cohorts SET status = ? WHERE cohort_id = ?", (status, cohort_id))


def set_cohort_start(cohort_id, start_date):
    with conn:
        conn.execute("UPDATE cohorts SET start_date = ? WHERE cohort_id = ?", (start_date, cohort_id))


def get_enrollment(cohort_id, user_id):
    return conn.execute(
        "SELECT * FROM enrollments WHERE cohort_id = ? AND user_id = ?", (cohort_id, str(user_id))
    ).fetchone()


def is_enrolled(cohort_id, user_id):
    row = get_enrollment(cohort_id, user_id)
    return bool(row) and row["left_at"] is None


def count_enrolled(cohort_id):
    return conn.execute(
        "SELECT COUNT(*) FROM enrollments WHERE cohort_id = ? AND left_at IS NULL", (cohort_id,)
    ).fetchone()[0]


def enroll(cohort_id, user_id):
    ensure_user(user_id)
    with conn:
        conn.execute(
            "INSERT INTO enrollments (cohort_id, user_id) VALUES (?, ?) "
            "ON CONFLICT(cohort_id, user_id) DO UPDATE SET left_at = NULL",
            (cohort_id, str(user_id)),
        )


def leave(cohort_id, user_id):
    with conn:
        conn.execute(
            "UPDATE enrollments SET left_at = datetime('now') WHERE cohort_id = ? AND user_id = ?",
            (cohort_id, str(user_id)),
        )


def get_submission(cohort_id, user_id, day):
    return conn.execute(
        "SELECT * FROM submissions WHERE cohort_id = ? AND user_id = ? AND day = ?",
        (cohort_id, str(user_id), day),
    ).fetchone()


def count_submissions(cohort_id, day):
    return conn.execute(
        "SELECT COUNT(*) FROM submissions WHERE cohort_id = ? AND day = ?", (cohort_id, day)
    ).fetchone()[0]


# ----------------------
# Илгээлт, bonus, leaderboard
# ----------------------
def save_submission(cohort_id, user_id, day, body, body_hash, word_count):
    """True = шинээр үүсгэв, False = засав. Дунд нь await байхгүй тул event loop дээр атомик."""
    uid = str(user_id)
    with conn:
        row = conn.execute(
            "SELECT id FROM submissions WHERE cohort_id = ? AND user_id = ? AND day = ?",
            (cohort_id, uid, day),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE submissions SET body = ?, body_hash = ?, word_count = ?, edited_at = datetime('now') WHERE id = ?",
                (body, body_hash, word_count, row["id"]),
            )
            return False
        conn.execute(
            "INSERT INTO submissions (cohort_id, user_id, day, body, body_hash, word_count) VALUES (?, ?, ?, ?, ?, ?)",
            (cohort_id, uid, day, body, body_hash, word_count),
        )
        return True


def submitted_days(cohort_id, user_id):
    rows = conn.execute(
        "SELECT day FROM submissions WHERE cohort_id = ? AND user_id = ?", (cohort_id, str(user_id))
    ).fetchall()
    return {r["day"] for r in rows}


def duplicate_exists(cohort_id, day, body_hash, user_id):
    return bool(conn.execute(
        "SELECT 1 FROM submissions WHERE cohort_id = ? AND day = ? AND body_hash = ? AND user_id <> ?",
        (cohort_id, day, body_hash, str(user_id)),
    ).fetchone())


def pending_publication(cohort_id, before_day, limit=15):
    return conn.execute(
        "SELECT * FROM submissions WHERE cohort_id = ? AND day < ? AND post_id IS NULL "
        "ORDER BY day, created_at LIMIT ?",
        (cohort_id, before_day, limit),
    ).fetchall()


def set_post_id(submission_id, post_id):
    with conn:
        conn.execute("UPDATE submissions SET post_id = ? WHERE id = ?", (str(post_id), submission_id))


def has_event(user_id, cohort_id, source):
    return bool(conn.execute(
        "SELECT 1 FROM exp_events WHERE user_id = ? AND cohort_id = ? AND source = ?",
        (str(user_id), cohort_id, source),
    ).fetchone())


def perfect_week_users(cohort_id, first_day, last_day):
    rows = conn.execute(
        "SELECT user_id FROM submissions WHERE cohort_id = ? AND day BETWEEN ? AND ? "
        "GROUP BY user_id HAVING COUNT(DISTINCT day) = ?",
        (cohort_id, first_day, last_day, last_day - first_day + 1),
    ).fetchall()
    return [r["user_id"] for r in rows]


def count_not_submitted(cohort_id, day):
    return conn.execute(
        "SELECT COUNT(*) FROM enrollments e WHERE e.cohort_id = ? AND e.left_at IS NULL AND NOT EXISTS "
        "(SELECT 1 FROM submissions s WHERE s.cohort_id = e.cohort_id AND s.user_id = e.user_id AND s.day = ?)",
        (cohort_id, day),
    ).fetchone()[0]


def cohort_board(cohort_id, limit=None):
    """Cohort-ийн оноогоор эрэмбэлсэн жагсаалт. Тэнцвэл: илүү олон өдөр, дараа нь эрт бүртгүүлсэн."""
    sql = (
        "SELECT e.user_id AS user_id, SUM(e.amount) AS exp, "
        " (SELECT COUNT(*) FROM submissions s WHERE s.cohort_id = e.cohort_id AND s.user_id = e.user_id) AS days_done, "
        " u.display_name AS display_name, u.avatar_url AS avatar_url, u.anonymous AS anonymous "
        "FROM exp_events e "
        "JOIN users u ON u.user_id = e.user_id "
        "JOIN enrollments en ON en.cohort_id = e.cohort_id AND en.user_id = e.user_id AND en.left_at IS NULL "
        "WHERE e.cohort_id = ? "
        "GROUP BY e.user_id ORDER BY exp DESC, days_done DESC, en.joined_at ASC"
    )
    args = (cohort_id,)
    if limit:
        sql += " LIMIT ?"
        args = (cohort_id, limit)
    return conn.execute(sql, args).fetchall()


# ----------------------
# State устгах, main board bonus, library
# ----------------------
def state_delete(key):
    with conn:
        conn.execute("DELETE FROM bot_state WHERE key = ?", (key,))


def has_main_event(user_id, source):
    return bool(conn.execute(
        "SELECT 1 FROM exp_events WHERE user_id = ? AND cohort_id IS NULL AND source = ?",
        (str(user_id), source),
    ).fetchone())


def library_get(user_id, program_id):
    return conn.execute(
        "SELECT * FROM library_enrollments WHERE user_id = ? AND program_id = ?", (str(user_id), program_id)
    ).fetchone()


def library_list(user_id):
    return conn.execute(
        "SELECT * FROM library_enrollments WHERE user_id = ? ORDER BY started_at", (str(user_id),)
    ).fetchall()


def library_start(user_id, program_id):
    ensure_user(user_id)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO library_enrollments (user_id, program_id) VALUES (?, ?)",
            (str(user_id), program_id),
        )


def library_done_days(user_id, program_id):
    rows = conn.execute(
        "SELECT day FROM library_progress WHERE user_id = ? AND program_id = ?", (str(user_id), program_id)
    ).fetchall()
    return {r["day"] for r in rows}


def library_complete_day(user_id, program_id, day, next_unlock_at):
    """Зөвхөн current_day таарвал дуусгана. Давхар дарвал False."""
    uid = str(user_id)
    with conn:
        cur = conn.execute(
            "UPDATE library_enrollments SET current_day = ?, next_unlock_at = ? "
            "WHERE user_id = ? AND program_id = ? AND current_day = ?",
            (day + 1, next_unlock_at, uid, program_id, day),
        )
        if cur.rowcount == 0:
            return False
        conn.execute(
            "INSERT OR IGNORE INTO library_progress (user_id, program_id, day) VALUES (?, ?, ?)",
            (uid, program_id, day),
        )
        return True
