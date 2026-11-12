"""Бүх тохиргоо нэг дор. Тоо өөрчлөх бол зөвхөн энэ файлыг засна."""
from zoneinfo import ZoneInfo

UB = ZoneInfo("Asia/Ulaanbaatar")

# ----------------------
# Цаг
# ----------------------
ROLLOVER_HOUR = 6   # Шинэ өдөр UB цагаар 06:00-д эхэлнэ
REMINDER_HOUR = 20  # Сануулга (2-р шатанд хэрэглэнэ)

# ----------------------
# Cohort
# ----------------------
DEFAULT_DAYS = 28
DEFAULT_MIN_SEATS = 10   # Үүнээс цөөн бол эхлэхгүй, хойшлуулна
DEFAULT_MAX_SEATS = 40
JOIN_CUTOFF_DAY = 3      # Өдөр 3 хүртэл /join хийж болно
POSTPONE_DAYS = 7        # Хүн хүрэлцээгүй бол хэд хоногоор хойшлуулах

# ----------------------
# Даалгавар (2-р шатанд хэрэглэнэ)
# ----------------------
WORD_MIN = 30
WORD_MAX = 80

# ----------------------
# Cohort EXP (2, 3-р шатанд хэрэглэнэ)
# ----------------------
EXP_SUBMIT = 50
EXP_STREAK_STEP = 2      # Дараалсан өдөр бүрт +2
EXP_STREAK_MAX = 10
EXP_PERFECT_WEEK = 30
EXP_FEATURED = 20
GRADUATE_MIN_DAYS = 22
BONUS_GRADUATE = 200     # Main board руу
BONUS_TOP3 = 150
BONUS_TOP10 = 100

# ----------------------
# Одоо байгаа командууд
# ----------------------
QUIZ_DAILY_LIMIT = 3
QUIZ_TIMEOUT = 30
QUIZ_EXP = 20
CHECKIN_EXP = 10
STREAK_MILESTONES = {7: 30, 30: 150, 100: 500}  # streak өдөр -> bonus EXP
TEST_BASE_URL = "https://anthonythesabakumono.github.io/Static_LanguageProficienfyTests/test.html"

# ----------------------
# Leaderboard
# ----------------------
LEADERBOARD_REFRESH_MINUTES = 3
