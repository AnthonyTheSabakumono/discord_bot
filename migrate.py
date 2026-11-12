import json
import os

import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "data.json"), encoding="utf-8") as f:
    old = json.load(f)

db.init_db()
for uid, u in old.items():
    quiz = u.get("quiz", {})
    with db.conn:
        db.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, checkin_streak, last_checkin, quiz_date, quiz_count, recent_quiz) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uid, u.get("checkinStreak", 0), u.get("lastCheckin"), quiz.get("date"),
             quiz.get("count", 0), json.dumps(u.get("recentQuiz", []))),
        )
        exp = u.get("exp", 0)
        done = db.conn.execute(
            "SELECT 1 FROM exp_events WHERE user_id = ? AND source = 'legacy'", (uid,)
        ).fetchone()
        if exp and not done:
            db.conn.execute(
                "INSERT INTO exp_events (user_id, source, amount) VALUES (?, 'legacy', ?)", (uid, exp)
            )
print(f"Шилжүүлсэн хэрэглэгч: {len(old)}")
