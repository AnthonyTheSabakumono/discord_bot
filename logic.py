"""Discord-оос хамааралгүй цагийн логик. Тест хийхэд хялбар."""
import hashlib
import math
import re
from datetime import date, datetime, timedelta

import config


def now_ub():
    return datetime.now(config.UB)


def ub_today(now=None):
    """UB-ийн хуанлийн өдөр (YYYY-MM-DD)."""
    return (now or now_ub()).date().isoformat()


def day_key(now=None):
    """Хөтөлбөрийн өдөр: UB 06:00-ээс өмнө бол өмнөх өдөрт тооцно."""
    now = now or now_ub()
    return (now - timedelta(hours=config.ROLLOVER_HOUR)).date()


def checkin_key(days_ago=0, now=None):
    return (day_key(now) - timedelta(days=days_ago)).isoformat()


def start_moment(start_date_str):
    """Cohort эхлэх агшин: эхлэх өдрийн 06:00 UB."""
    d = date.fromisoformat(start_date_str)
    return datetime(d.year, d.month, d.day, config.ROLLOVER_HOUR, tzinfo=config.UB)


def cohort_day(start_date_str, now=None):
    """0 эсвэл сөрөг = эхлээгүй, 1.. = явагдаж буй өдөр."""
    start = date.fromisoformat(start_date_str)
    return (day_key(now) - start).days + 1


def day_deadline(start_date_str, day):
    """N-р өдрийн дуусах хугацаа = эхлэх өдөр + N хоногийн 06:00 UB."""
    return start_moment(start_date_str) + timedelta(days=day)


# ----------------------
# Илгээлтийн туслахууд
# ----------------------
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")


def clean_text(text):
    text = re.sub(r"[^\S\n]+", " ", text).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def count_words(text):
    """Англи үг тоолно (кирилл үг тооцогдохгүй)."""
    return len(_WORD_RE.findall(text))


def text_hash(text):
    """Том/жижиг үсэг, цэг тэмдэглэгээг үл хамааран ижил эсэхийг шалгах хэш."""
    norm = " ".join(_WORD_RE.findall(text.lower()))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def streak_length(days, upto):
    """upto өдрөөс хойш нь дараалсан илгээсэн өдрийн тоо."""
    n, d = 0, upto
    while d >= 1 and d in days:
        n += 1
        d -= 1
    return n


def streak_bonus(streak):
    if streak <= 1:
        return 0
    return min(config.EXP_STREAK_STEP * (streak - 1), config.EXP_STREAK_MAX)


def hint_lines(text, hints):
    low = text.lower()
    return [
        ("✅ " if any(k.lower() in low for k in h["keywords"]) else "⬜ ") + h["label"]
        for h in hints
    ]


def chunk_lines(lines, limit=1000):
    chunks, cur = [], ""
    for line in lines:
        if cur and len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def progress_track(total, done, day):
    """7 өдөр тутамд нэг мөр: 🟩 илгээсэн, ⬛ алгассан, ⬜ ирээгүй."""
    rows = []
    for w in range((total + 6) // 7):
        cells = []
        for d in range(w * 7 + 1, min(w * 7 + 7, total) + 1):
            cells.append("🟩" if d in done else "⬛" if d < day else "⬜")
        rows.append(f"`{w + 1}-р долоо хоног` " + "".join(cells))
    return "\n".join(rows)


# ----------------------
# Cohort хаалт, library
# ----------------------
def graduate_min_days(total):
    """28 өдөрт 22. Өөр урттай бол ижил харьцаагаар."""
    return math.ceil(total * config.GRADUATE_MIN_DAYS / 28)


def next_unlock(now=None):
    """Дараагийн хөтөлбөрийн өдрийн эхлэл (06:00 UB)."""
    return start_moment((day_key(now) + timedelta(days=1)).isoformat())


def library_state(current_day, next_unlock_iso, total_days, now=None):
    """('finished'|'locked'|'open', unlock_datetime_or_None)"""
    if current_day > total_days:
        return "finished", None
    if next_unlock_iso:
        unlock = datetime.fromisoformat(next_unlock_iso)
        if (now or now_ub()) < unlock:
            return "locked", unlock
    return "open", None
