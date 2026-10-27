import json
import os
import random
import shutil
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise SystemExit("TOKEN .env файлд алга байна")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")
QUIZ_FILE = os.path.join(BASE_DIR, "english.json")
UB = ZoneInfo("Asia/Ulaanbaatar")

# ----------------------
# Quiz data
# ----------------------
try:
    with open(QUIZ_FILE, encoding="utf-8") as f:
        quiz_data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    quiz_data = []
    print("english.json not found")


# ----------------------
# Data (loaded once, kept in memory)
# ----------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"data.json уншихад алдаа, нөөц үүсгэлээ: {e}")
        shutil.copy(DATA_FILE, f"{DATA_FILE}.broken-{int(time.time())}")
        return {}


data = load_data()


def save_data():
    # Atomic save: write temp file, then replace
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)


def get_user(user_id):
    return data.setdefault(str(user_id), {})


def add_exp(user, amount):
    user["exp"] = user.get("exp", 0) + amount
    user["level"] = user["exp"] // 100 + 1


# ----------------------
# Date helpers (Ulaanbaatar time)
# ----------------------
def ub_today():
    return datetime.now(UB).date().isoformat()


def checkin_key(days_ago=0):
    # Check-in day starts at 06:00 UB time
    d = datetime.now(UB) - timedelta(hours=6, days=days_ago)
    return d.date().isoformat()


# ----------------------
# Quiz buttons
# ----------------------
class QuizView(discord.ui.View):
    def __init__(self, question, user_id):
        super().__init__(timeout=15)
        self.q = question
        self.user_id = user_id
        self.message = None
        self.answered = False

        for i, opt in enumerate(question["options"]):
            button = discord.ui.Button(
                label=str(opt)[:80], style=discord.ButtonStyle.primary
            )
            button.callback = self.make_callback(i)
            self.add_item(button)

    def make_callback(self, index):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    "Энэ quiz чинийх биш.", ephemeral=True
                )
                return

            self.answered = True
            self.stop()

            if index == self.q["answer"]:
                add_exp(get_user(self.user_id), 20)
                save_data()
                await interaction.response.edit_message(
                    content="✅ Зөв! +20 EXP", view=None
                )
            else:
                correct = self.q["options"][self.q["answer"]]
                await interaction.response.edit_message(
                    content=f"❌ Буруу! Зөв: {correct}", view=None
                )

        return callback

    async def on_timeout(self):
        if not self.answered and self.message:
            try:
                await self.message.edit(
                    content="⏰ Цаг дууслаа! Quiz дууссан.", view=None
                )
            except discord.HTTPException:
                pass


# ----------------------
# Discord client
# ----------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip()
    if not content.startswith("!"):
        return

    user_id = message.author.id
    user = get_user(user_id)

    try:
        # -------- !profile --------
        if content == "!profile":
            await message.reply(
                f"👤 Profile\n\n"
                f"⭐ Level: {user.get('level', 1)}\n"
                f"⚡ EXP: {user.get('exp', 0)}\n"
                f"🔥 Streak: {user.get('checkinStreak', 0)}"
            )

        # -------- !test --------
        elif content.startswith("!test"):
            args = content.split()
            test_type = "japanese" if len(args) > 1 and args[1] == "japanese" else "english"
            url = (
                "https://akitothesabakumono.github.io/Test2/test.html"
                f"?test={test_type}&userId={user_id}"
            )
            await message.reply(f"Тестээ эндээс хийж болно:\n{url}")

        # -------- !leaderboard --------
        elif content == "!leaderboard":
            top = sorted(data.items(), key=lambda kv: kv[1].get("exp", 0), reverse=True)[:10]
            text = "🏆 Leaderboard:\n"
            for i, (uid, u) in enumerate(top, 1):
                text += f"\n{i}. <@{uid}> - {u.get('exp', 0)} EXP"
            await message.reply(text, allowed_mentions=discord.AllowedMentions.none())

        # -------- !quiz --------
        elif content == "!quiz":
            if not quiz_data:
                await message.reply("❌ Quiz data алга байна")
                return

            today = ub_today()
            quiz = user.get("quiz")
            if not quiz or quiz.get("date") != today:
                quiz = user["quiz"] = {"date": today, "count": 0}

            if quiz["count"] >= 3:
                await message.reply("⛔ Өнөөдрийн quiz лимит (3)")
                return

            # Count when asked, so opening many quizzes at once can't bypass the limit
            quiz["count"] += 1
            save_data()

            q = random.choice(quiz_data)
            view = QuizView(q, user_id)
            view.message = await message.reply(f"❓ {q['question']}", view=view)

        # -------- !checkin --------
        elif content == "!checkin":
            today = checkin_key(0)
            yesterday = checkin_key(1)

            if not user.get("lastCheckin"):
                user["lastCheckin"] = today
                user["checkinStreak"] = 1
                add_exp(user, 10)
                save_data()
                await message.reply("🎉 Анхны check-in! +10 EXP")

            elif user["lastCheckin"] == today:
                await message.reply("⏰ Аль хэдийн check-in хийсэн")

            else:
                if user["lastCheckin"] == yesterday:
                    user["checkinStreak"] = user.get("checkinStreak", 0) + 1
                else:
                    user["checkinStreak"] = 1
                user["lastCheckin"] = today
                add_exp(user, 10)
                save_data()
                await message.reply(
                    f"🎉 Check-in! Стрик: {user['checkinStreak']} (+10 EXP)"
                )

    except Exception as e:
        print(f"Command error: {e}")


client.run(TOKEN)
