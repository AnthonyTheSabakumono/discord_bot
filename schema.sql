CREATE TABLE IF NOT EXISTS users (
  user_id        TEXT PRIMARY KEY,
  display_name   TEXT,
  checkin_streak INTEGER NOT NULL DEFAULT 0,
  last_checkin   TEXT,
  quiz_date      TEXT,
  quiz_count     INTEGER NOT NULL DEFAULT 0,
  recent_quiz    TEXT NOT NULL DEFAULT '[]',
  anonymous      INTEGER NOT NULL DEFAULT 0,
  avatar_url     TEXT,
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- EXP бүр нэг мөр. cohort_id NULL = main board, утгатай = тухайн cohort-ийн оноо.
CREATE TABLE IF NOT EXISTS exp_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    TEXT NOT NULL REFERENCES users(user_id),
  source     TEXT NOT NULL,
  amount     INTEGER NOT NULL,
  cohort_id  TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_exp_user ON exp_events(user_id);

-- status: scheduled -> running -> finished -> closed
CREATE TABLE IF NOT EXISTS cohorts (
  cohort_id       TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  program_id      TEXT NOT NULL,
  start_date      TEXT NOT NULL,
  days            INTEGER NOT NULL DEFAULT 28,
  min_seats       INTEGER NOT NULL DEFAULT 10,
  max_seats       INTEGER NOT NULL DEFAULT 40,
  join_cutoff_day INTEGER NOT NULL DEFAULT 3,
  status          TEXT NOT NULL DEFAULT 'scheduled'
);

CREATE TABLE IF NOT EXISTS enrollments (
  cohort_id TEXT NOT NULL REFERENCES cohorts(cohort_id),
  user_id   TEXT NOT NULL REFERENCES users(user_id),
  joined_at TEXT NOT NULL DEFAULT (datetime('now')),
  left_at   TEXT,
  PRIMARY KEY (cohort_id, user_id)
);

-- Нэг өдөрт нэг илгээлт. Cohort-ийн ахиц эндээс тооцогдоно.
CREATE TABLE IF NOT EXISTS submissions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  cohort_id  TEXT NOT NULL REFERENCES cohorts(cohort_id),
  user_id    TEXT NOT NULL REFERENCES users(user_id),
  day        INTEGER NOT NULL,
  body       TEXT NOT NULL,
  body_hash  TEXT NOT NULL,
  word_count INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  edited_at  TEXT,
  post_id    TEXT,
  UNIQUE (cohort_id, user_id, day)
);
CREATE INDEX IF NOT EXISTS idx_sub_day ON submissions(cohort_id, day);

CREATE TABLE IF NOT EXISTS library_enrollments (
  user_id        TEXT NOT NULL REFERENCES users(user_id),
  program_id     TEXT NOT NULL,
  started_at     TEXT NOT NULL DEFAULT (datetime('now')),
  current_day    INTEGER NOT NULL DEFAULT 1,
  next_unlock_at TEXT,
  PRIMARY KEY (user_id, program_id)
);

CREATE TABLE IF NOT EXISTS library_progress (
  user_id    TEXT NOT NULL,
  program_id TEXT NOT NULL,
  day        INTEGER NOT NULL,
  done_at    TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (user_id, program_id, day)
);

CREATE TABLE IF NOT EXISTS bot_state (
  key   TEXT PRIMARY KEY,
  value TEXT
);
