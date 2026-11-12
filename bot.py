import asyncio
import json
import os
import random
from datetime import date, timedelta
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

import config
import db
import logic

load_dotenv()
TOKEN = os.getenv("TOKEN")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUIZ_FILE = os.path.join(BASE_DIR, "english.json")
PROGRAMS_FILE = os.path.join(BASE_DIR, "programs.json")

GOLD = discord.Color.from_str("#C9A84C")


# ----------------------
# Өгөгдөл: quiz, programs
# ----------------------
try:
    with open(QUIZ_FILE, encoding="utf-8") as f:
        quiz_data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    quiz_data = []
    print("english.json олдсонгүй эсвэл формат буруу")

try:
    with open(PROGRAMS_FILE, encoding="utf-8") as f:
        programs = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    programs = {}
    print("programs.json олдсонгүй эсвэл формат буруу")


def page_url(cohort, day):
    p = programs.get(cohort["program_id"])
    return f"{p['pages_url']}?day={day}" if p else None


def private_day(cohort, day):
    """Зөвхөн bot-д харагдах өдрийн өгөгдөл (private/<program>/day-NN.json)."""
    p = programs.get(cohort["program_id"])
    if not p:
        return {}
    path = os.path.join(BASE_DIR, p["private_dir"], f"day-{day:02d}.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ----------------------
# Embed helpers
# ----------------------
def progress_bar(exp, width=10):
    filled = (exp % 100) * width // 100
    return "▰" * filled + "▱" * (width - filled)


def info_embed(text, color=discord.Color.blurple(), title=None):
    return discord.Embed(title=title, description=text, color=color)


def error_embed(text):
    return discord.Embed(description=text, color=discord.Color.red())


def question_embed(q, remaining):
    embed = discord.Embed(
        title="❓ Quiz",
        description=f"**{q['question']}**",
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"{config.QUIZ_TIMEOUT} секундийн дотор хариулна уу • Өнөөдөр үлдсэн: {remaining}")
    return embed


def answer_embed(q, correct, leveled_up, new_level):
    right = q["options"][q["answer"]]
    if correct:
        embed = discord.Embed(
            title="✅ Зөв!", description=f"+{config.QUIZ_EXP} EXP", color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title="❌ Буруу", description=f"Зөв хариулт: **{right}**", color=discord.Color.red()
        )
    embed.add_field(name="Асуулт", value=q["question"], inline=False)
    if q.get("explanation"):
        embed.add_field(name="💡 Тайлбар", value=str(q["explanation"])[:1000], inline=False)
    if leveled_up:
        embed.add_field(name="🎉 Level up!", value=f"Чи одоо **Level {new_level}** боллоо!", inline=False)
    return embed


# ----------------------
# Quiz buttons
# ----------------------
class QuizView(discord.ui.View):
    def __init__(self, question, user_id):
        super().__init__(timeout=config.QUIZ_TIMEOUT)
        self.q = question
        self.user_id = user_id
        self.message = None
        self.answered = False

        for i, opt in enumerate(question["options"]):
            button = discord.ui.Button(
                label=f"{i + 1}. {opt}"[:80], style=discord.ButtonStyle.primary
            )
            button.callback = self.make_callback(i)
            self.add_item(button)

    def make_callback(self, index):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    "Энэ quiz чинийх биш. `/quiz` гэж бичээд өөрийнхөө quiz-ийг эхлүүл.",
                    ephemeral=True,
                )
                return
            if self.answered:
                await interaction.response.send_message("Энэ quiz дууссан байна.", ephemeral=True)
                return

            self.answered = True
            self.stop()

            correct = index == self.q["answer"]
            leveled_up = False
            if correct:
                leveled_up = db.add_exp(self.user_id, "quiz", config.QUIZ_EXP)
            level = db.level_of(db.total_exp(self.user_id))

            await interaction.response.edit_message(
                embed=answer_embed(self.q, correct, leveled_up, level), view=None
            )

        return callback

    async def on_timeout(self):
        if self.answered or not self.message:
            return
        self.answered = True
        try:
            await self.message.edit(
                embed=discord.Embed(
                    title="⏰ Цаг дууслаа!",
                    description=f"Зөв хариулт: **{self.q['options'][self.q['answer']]}**",
                    color=discord.Color.orange(),
                ),
                view=None,
            )
        except discord.HTTPException:
            pass


# ----------------------
командууд
# ----------------------
def cmd_profile(member):
    user = db.ensure_user(member.id, member.display_name, member.display_avatar.url)
    exp = db.total_exp(member.id)
    level = db.level_of(exp)
    embed = discord.Embed(
        description=(
            f"**⭐ Level {level}**\n"
            f"**{exp}** EXP  ·  🔥 **{user['checkin_streak']}** өдрийн streak\n\n"
            f"{progress_bar(exp)}  {exp % 100}/100"
        ),
        color=discord.Color.blurple(),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.set_footer(text=f"Дараагийн level хүртэл {100 - exp % 100} EXP")
    return embed, None


def cmd_leaderboard():
    top = db.leaderboard(10)
    if not top:
        return info_embed("Одоогоор хэн ч EXP авоогүй байна."), None
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, row in enumerate(top):
        prefix = medals[i] if i < 3 else f"`{i + 1}.`"
        lines.append(f"{prefix} <@{row['user_id']}> — **{row['exp']}** EXP (Lv {db.level_of(row['exp'])})")
    return info_embed("\n".join(lines), title="🏆 Leaderboard", color=discord.Color.gold()), None


def cmd_test(language):
    url = f"{config.TEST_BASE_URL}?test={language}"
    label = "Япон хэл" if language == "japanese" else "Англи хэл"
    return info_embed(f"[{label}-ний тест эхлүүлэх]({url})", title="📝 Түвшин тогтоох тест"), None


def cmd_checkin(member):
    user = db.ensure_user(member.id, member.display_name, member.display_avatar.url)
    today = logic.checkin_key(0)
    yesterday = logic.checkin_key(1)

    if user["last_checkin"] == today:
        return info_embed(
            "⏰ Өнөөдөр check-in хийсэн байна. Маргааш 06:00-с хойш дахин ир.",
            color=discord.Color.orange(),
        ), None

    streak = user["checkin_streak"] + 1 if user["last_checkin"] == yesterday else 1
    db.update_user(member.id, checkin_streak=streak, last_checkin=today)

    bonus = config.STREAK_MILESTONES.get(streak, 0)
    gained = config.CHECKIN_EXP + bonus
    leveled_up = db.add_exp(member.id, "checkin", gained)

    embed = discord.Embed(
        title="🎉 Check-in амжилттай",
        description=f"🔥 Streak: **{streak}** өдөр\n+{gained} EXP",
        color=discord.Color.green(),
    )
    if bonus:
        embed.add_field(name="🏅 Streak шагнал", value=f"{streak} өдрийн bonus +{bonus} EXP", inline=False)
    if leveled_up:
        level = db.level_of(db.total_exp(member.id))
        embed.add_field(name="🎉 Level up!", value=f"Чи одоо **Level {level}** боллоо!", inline=False)
    return embed, None


def cmd_quiz(member):
    if not quiz_data:
        return error_embed("❌ Quiz data алга байна"), None

    user = db.ensure_user(member.id, member.display_name, member.display_avatar.url)
    today = logic.ub_today()
    count = user["quiz_count"] if user["quiz_date"] == today else 0

    if count >= config.QUIZ_DAILY_LIMIT:
        return info_embed(
            f"⛔ Өнөөдрийн quiz лимит ({config.QUIZ_DAILY_LIMIT}) дууссан. Маргааш дахин ир!",
            color=discord.Color.orange(),
        ), None

    recent = json.loads(user["recent_quiz"] or "[]")
    pool = [i for i in range(len(quiz_data)) if i not in recent]
    if not pool:
        pool = list(range(len(quiz_data)))
        recent = []
    idx = random.choice(pool)


    db.update_user(
        member.id,
        quiz_date=today,
        quiz_count=count + 1,
        recent_quiz=json.dumps((recent + [idx])[-10:]),
    )

    q = quiz_data[idx]
    remaining = config.QUIZ_DAILY_LIMIT - (count + 1)
    return question_embed(q, remaining), QuizView(q, member.id)


# ----------------------
#helper
# ----------------------
async def send(target, embed, view=None):
    kwargs = {"embed": embed}
    if view is not None:
        kwargs["view"] = view

    if isinstance(target, discord.Interaction):
        await target.response.send_message(**kwargs)
        msg = await target.original_response()
    else:
        msg = await target.reply(**kwargs)

    if view is not None:
        view.message = msg


async def private(interaction, embed):
    """Зөвхөн тухайн хүнд харагдах хариу. defer хийсэн эсэхийг өөрөө шалгана."""
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ----------------------
# Discord client
# ----------------------
intents = discord.Intents.default()
intents.message_content = True  # зөвхөн !prefix командуудад хэрэгтэй


class LearningClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        rollover_loop.start()
        leaderboard_loop.start()

    async def on_ready(self):
        print(f"Logged in as {self.user}")


client = LearningClient()
db.init_db()


# ----------------------
# Cohort
# ----------------------
def ts(dt, style="F"):
    return f"<t:{int(dt.timestamp())}:{style}>"


def today_embed(cohort, day):
    url = page_url(cohort, day)
    title = private_day(cohort, day).get("title")
    head = f"📘 Өдөр {day}/{cohort['days']}" + (f" — {title}" if title else "")
    deadline = logic.day_deadline(cohort["start_date"], day)

    parts = []
    parts.append(f"[Өнөөдрийн хуудас руу орох]({url})" if url else "Хуудасны холбоос тохируулаагүй байна.")
    parts.append("Сүүлийн даалгавраа `/submit` командаар илгээнэ.")
    parts.append(f"Дуусах хугацаа: {ts(deadline)} ({ts(deadline, 'R')})")
    return discord.Embed(title=head, description="\n\n".join(parts), color=GOLD)


async def get_channel_by_state(key):
    cid = db.state_get(key)
    if not cid:
        return None
    channel = client.get_channel(int(cid))
    if channel is None:
        try:
            channel = await client.fetch_channel(int(cid))
        except discord.HTTPException:
            return None
    return channel


async def notify_admin(text):
    admin_id = db.state_get("admin_id")
    if not admin_id:
        return
    try:
        user = await client.fetch_user(int(admin_id))
        await user.send(embed=info_embed(text, title="⚙️ Cohort"))
    except discord.HTTPException as e:
        print(f"Админд мэдэгдэж чадсангүй: {e}")


async def announce(text):
    channel = await get_channel_by_state("today_channel_id")
    if channel is None:
        return
    try:
        await channel.send(embed=info_embed(text, color=GOLD))
    except discord.HTTPException as e:
        print(f"Зарлал илгээж чадсангүй: {e}")


async def post_today(cohort, day, ping=True):
    """#today сувгийн ганц мессежийг тухайн өдрийн хуудас болгож засна."""
    channel = await get_channel_by_state("today_channel_id")
    if channel is None:
        print("today суваг тохируулаагүй байна (/admin setup)")
        return False

    embed = today_embed(cohort, day)
    msg = None
    msg_id = db.state_get("today_message_id")
    if msg_id:
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed)
        except discord.NotFound:
            msg = None
    if msg is None:
        msg = await channel.send(embed=embed)
        db.state_set("today_message_id", msg.id)

    if ping:
        role_id = db.state_get("cohort_role_id")
        role = channel.guild.get_role(int(role_id)) if role_id else None
        if role:
            try:
                await channel.send(
                    content=f"{role.mention} Өдөр {day} нээгдлээ!",
                    allowed_mentions=discord.AllowedMentions(roles=[role]),
                    delete_after=60,
                )
            except discord.HTTPException:
                pass
    return True


# ----------------------
# Өдөр бүрийн шилжилт.
# ----------------------
async def run_rollover(cohort):
    day = logic.cohort_day(cohort["start_date"])
    status = cohort["status"]

    if status == "scheduled":
        if day < 1:
            return
        enrolled = db.count_enrolled(cohort["cohort_id"])
        if enrolled < cohort["min_seats"]:
            new_start = logic.day_key() + timedelta(days=config.POSTPONE_DAYS)
            db.set_cohort_start(cohort["cohort_id"], new_start.isoformat())
            text = (
                f"Cohort эхлэхэд хүн хүрэлцсэнгүй ({enrolled}/{cohort['min_seats']}). "
                f"Шинэ эхлэх өдөр: **{new_start.isoformat()}** 06:00 (UB)."
            )
            await announce(text)
            await notify_admin(text + " Өөрчлөх бол `/admin cohort_postpone` ашиглана.")
            return
        db.set_cohort_status(cohort["cohort_id"], "running")
        status = "running"

    if status == "running":
        award_perfect_weeks(cohort, day)
        if 1 <= day <= cohort["days"]:
            await post_today(cohort, day)
        elif day > cohort["days"]:
            db.set_cohort_status(cohort["cohort_id"], "finished")
            await announce(f"🎓 **{cohort['name']}** дууслаа. Баяр хүргэе!")
            await notify_admin(f"{cohort['name']}-ийн сүүлийн өдөр дууслаа. Дүн гаргахыг хүлээж байна.")


async def rollover_tick():
    cohort = db.active_cohort()
    key = logic.day_key().isoformat()
    if db.state_get("last_rollover") != key:
        if cohort:
            await run_rollover(cohort)
        db.state_set("last_rollover", key)
        cohort = db.active_cohort()
  
    if cohort and cohort["status"] in ("running", "finished"):
        await publish_pending(cohort)
        await reminder_tick(cohort)


@tasks.loop(minutes=1)
async def rollover_loop():
    try:
        await rollover_tick()
    except Exception as e:
        print(f"Rollover алдаа: {e}")


@rollover_loop.before_loop
async def _before_rollover():
    await client.wait_until_ready()


# ----------------------
# prefix command
# ----------------------
@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    content = message.content.strip()
    if not content.startswith("!"):
        return

    parts = content.split()
    cmd = parts[0].lower()

    try:
        if cmd == "!profile":
            embed, view = cmd_profile(message.author)
        elif cmd == "!leaderboard":
            embed, view = cmd_leaderboard()
        elif cmd == "!quiz":
            embed, view = cmd_quiz(message.author)
        elif cmd == "!checkin":
            embed, view = cmd_checkin(message.author)
        elif cmd == "!test":
            lang = "japanese" if len(parts) > 1 and parts[1].lower() == "japanese" else "english"
            embed, view = cmd_test(lang)
        else:
            return
        await send(message, embed, view)
    except Exception as e:
        print(f"Command error ({cmd}): {e}")
        try:
            await message.reply(embed=error_embed("❌ Алдаа гарлаа. Дараа дахин оролдоорой."))
        except discord.HTTPException:
            pass


# ----------------------
# /slash 
# ----------------------
@client.tree.command(name="profile", description="Өөрийн түвшин, EXP болон ахицаа харах")
async def profile(interaction: discord.Interaction):
    embed, view = cmd_profile(interaction.user)
    await send(interaction, embed, view)


@client.tree.command(name="quiz", description=f"Англи хэлний quiz — өдөрт {config.QUIZ_DAILY_LIMIT} оролдлого")
async def quiz(interaction: discord.Interaction):
    embed, view = cmd_quiz(interaction.user)
    await send(interaction, embed, view)


@client.tree.command(name="checkin", description=f"Өдөр бүр check-in хийж +{config.CHECKIN_EXP} EXP авах")
async def checkin(interaction: discord.Interaction):
    embed, view = cmd_checkin(interaction.user)
    await send(interaction, embed, view)


@client.tree.command(name="leaderboard", description="Суралцагчдын EXP жагсаалтыг харах")
async def leaderboard(interaction: discord.Interaction):
    embed, view = cmd_leaderboard()
    await send(interaction, embed, view)


@client.tree.command(name="test", description="Англи эсвэл япон хэлний тест нээх")
async def test(interaction: discord.Interaction, language: Literal["english", "japanese"] = "english"):
    embed, view = cmd_test(language)
    await send(interaction, embed, view)


# ----------------------
# /slash: cohort командууд
# ----------------------
@client.tree.command(name="join", description="Cohort-д бүртгүүлж, өдөр бүрийн хөтөлбөрт орох")
@app_commands.guild_only()
async def join(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    member = interaction.user

    cohort = db.active_cohort()
    if not cohort or cohort["status"] == "finished":
        await private(interaction, info_embed("Одоогоор бүртгэл нээлттэй cohort алга."))
        return

    cid = cohort["cohort_id"]
    day = logic.cohort_day(cohort["start_date"])

    if db.is_enrolled(cid, member.id):
        await private(interaction, info_embed("Чи аль хэдийн бүртгүүлсэн байна. `/today` гэж бичээд өнөөдрийн хуудсаа үз."))
        return
    if day > cohort["join_cutoff_day"]:
        await private(interaction, info_embed(
            f"Бүртгэл Өдөр {cohort['join_cutoff_day']}-ээр хаагдсан. Дараагийн cohort-ийг хүлээнэ үү."
        ))
        return
    if db.count_enrolled(cid) >= cohort["max_seats"]:
        await private(interaction, info_embed("Уучлаарай, суудал дүүрсэн байна."))
        return

    role_id = db.state_get("cohort_role_id")
    role = interaction.guild.get_role(int(role_id)) if role_id else None
    if role is None:
        await private(interaction, error_embed("Cohort-ийн тохиргоо дутуу байна. Админд мэдэгдээрэй."))
        return

    try:
        await member.add_roles(role, reason=f"Cohort {cid} join")
    except discord.Forbidden:
        print("add_roles Forbidden: bot-ийн role cohort role-оос дээр байх ёстой")
        await private(interaction, error_embed("Role өгч чадсангүй. Админд мэдэгдээрэй."))
        return

    db.ensure_user(member.id, member.display_name, member.display_avatar.url)
    db.enroll(cid, member.id)

    if day < 1:
        start = logic.start_moment(cohort["start_date"])
        when = f"Cohort **{start.strftime('%Y-%m-%d')} 06:00 (UB)** цагт эхэлнэ ({ts(start, 'R')})."
    else:
        when = f"Cohort явагдаж байна. Өнөөдөр **Өдөр {day}**. `/today` гэж бичээд хуудсаа үз."

    text = (
        f"**{cohort['name']}**-д бүртгэгдлээ.\n\n{when}\n\n"
        "• Өдөр бүр 06:00 (UB) цагт шинэ хуудас нээгдэнэ, өмнөх өдрүүд хаагдана.\n"
        "• Өдрийн сүүлийн даалгавраа `/submit`-аар илгээнэ.\n"
        "• Хоцорсон өдрийг нөхөх боломжгүй, гэхдээ маргааш үргэлжлүүлж болно."
    )
    await private(interaction, info_embed(text, title="🎉 Тавтай морил", color=GOLD))


@client.tree.command(name="today", description="Өнөөдрийн хөтөлбөрийн хуудасны холбоос")
@app_commands.guild_only()
async def today(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    member = interaction.user

    cohort = db.active_cohort()
    if not cohort:
        await private(interaction, info_embed("Одоогоор идэвхтэй cohort алга."))
        return
    cid = cohort["cohort_id"]

    if not db.is_enrolled(cid, member.id):
        await private(interaction, info_embed("Эхлээд `/join` гэж бичиж cohort-д бүртгүүлнэ үү."))
        return

    day = logic.cohort_day(cohort["start_date"])
    status = cohort["status"]

    if status == "scheduled" and day < 1:
        start = logic.start_moment(cohort["start_date"])
        await private(interaction, info_embed(
            f"Cohort **{start.strftime('%Y-%m-%d')} 06:00 (UB)** цагт эхэлнэ ({ts(start, 'R')})."
        ))
    elif status == "scheduled":
        await private(interaction, info_embed("Cohort эхлэх гэж байна. Хэдхэн минутын дараа дахин оролдоно уу."))
    elif status == "running" and 1 <= day <= cohort["days"]:
        embed = today_embed(cohort, day)
        done = db.get_submission(cid, member.id, day)
        embed.add_field(name="Төлөв", value="✅ Илгээсэн" if done else "⬜ Одоохондоо илгээгээгүй", inline=False)
        await private(interaction, embed)
    else:
        await private(interaction, info_embed("Cohort дууссан байна."))


@client.tree.command(name="leave", description="Cohort-оос гарах")
@app_commands.guild_only()
async def leave(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    member = interaction.user
    cohort = db.active_cohort()
    if not cohort or not db.is_enrolled(cohort["cohort_id"], member.id):
        await private(interaction, info_embed("Чи cohort-д бүртгэлгүй байна."))
        return

    db.leave(cohort["cohort_id"], member.id)
    role_id = db.state_get("cohort_role_id")
    role = interaction.guild.get_role(int(role_id)) if role_id else None
    if role:
        try:
            await member.remove_roles(role, reason="Cohort leave")
        except discord.HTTPException:
            pass
    await private(interaction, info_embed("Cohort-оос гарлаа. Дараа дахин `/join` хийж болно (бүртгэл нээлттэй бол)."))


@client.tree.command(name="privacy", description="Leaderboard дээр нэрээ нууцлах / харуулах")
async def privacy(interaction: discord.Interaction):
    user = db.ensure_user(interaction.user.id, interaction.user.display_name, interaction.user.display_avatar.url)
    new_value = 0 if user["anonymous"] else 1
    db.update_user(interaction.user.id, anonymous=new_value)
    text = "Leaderboard дээр одоо **Anonymous** гэж харагдана." if new_value else "Leaderboard дээр нэр, зураг чинь харагдана."
    await private(interaction, info_embed(text))


# ----------------------
# Илгээлт (/submit)
# ----------------------
class SubmitError(Exception):
    """Хэрэглэгчид шууд харуулах алдаа."""


def process_submission(cohort, member, text, expected_day=None):
    """Илгээлтийг шалгаад хадгална. Үр дүнгийн dict буцаана, буруу бол SubmitError."""
    if not cohort or cohort["status"] != "running":
        raise SubmitError("Cohort одоогоор явагдахгүй байна.")
    cid = cohort["cohort_id"]
    day = logic.cohort_day(cohort["start_date"])
    if not 1 <= day <= cohort["days"]:
        raise SubmitError("Өнөөдөр илгээх өдөр биш байна.")
    if expected_day is not None and day != expected_day:
        raise SubmitError("Энэ өдрийн хугацаа дууссан байна. Шинэ өдрийн даалгаврыг `/today`-оос үзээд `/submit` хийнэ үү.")
    if not db.is_enrolled(cid, member.id):
        raise SubmitError("Эхлээд `/join` хийж cohort-д бүртгүүлнэ үү.")

    pday = private_day(cohort, day)
    lo = pday.get("min_words", config.WORD_MIN)
    hi = pday.get("max_words", config.WORD_MAX)
    text = logic.clean_text(text)
    words = logic.count_words(text)
    if words < lo or words > hi:
        raise SubmitError(
            f"Хариу англиар, **{lo}–{hi} үгтэй** байх ёстой. Одоо {words} үг байна. "
            "`/submit`-ээр дахин бичнэ үү."
        )
    body_hash = logic.text_hash(text)
    if db.duplicate_exists(cid, day, body_hash, member.id):
        raise SubmitError("Энэ хариу өөр хүний хариутай яг ижил байна. Өөрийнхөөрөө бичнэ үү.")

    db.ensure_user(member.id, member.display_name, member.display_avatar.url)
    created = db.save_submission(cid, member.id, day, text, body_hash, words)
    gained = []
    if created:
        db.add_exp(member.id, "submit", config.EXP_SUBMIT, cohort_id=cid)
        gained.append(("Илгээлт", config.EXP_SUBMIT))
        streak = logic.streak_length(db.submitted_days(cid, member.id), day)
        bonus = logic.streak_bonus(streak)
        if bonus:
            db.add_exp(member.id, "streak", bonus, cohort_id=cid)
            gained.append((f"Streak {streak} өдөр", bonus))
    return {"day": day, "words": words, "created": created, "gained": gained, "text": text, "pday": pday}


def submission_embed(result):
    pday = result["pday"]
    embed = discord.Embed(
        title="✅ Илгээгдлээ" if result["created"] else "✏️ Засагдлаа",
        description=(
            "Хариу чинь маргааш 06:00 (UB) цагт бусдад харагдана. "
            "Хугацаа дуусахаас өмнө `/submit`-ээр дахин засаж болно."
        ),
        color=discord.Color.green(),
    )
    embed.add_field(name="Үгийн тоо", value=str(result["words"]))
    if result["gained"]:
        embed.add_field(name="EXP", value="\n".join(f"+{n} — {label}" for label, n in result["gained"]))
    else:
        embed.add_field(name="EXP", value="Засвар нэмэлт EXP өгөхгүй")

    if pday.get("hints"):
        embed.add_field(
            name="Шалгах жагсаалт (зөвлөмж)",
            value="\n".join(logic.hint_lines(result["text"], pday["hints"])),
            inline=False,
        )
    add_key_fields(embed, pday)
    return embed


class SubmitModal(discord.ui.Modal):
    def __init__(self, cohort, day, existing=""):
        super().__init__(title=f"Өдөр {day} — даалгавар"[:45])
        self.day = day
        self.answer = discord.ui.TextInput(
            label="Хариу (англиар)",
            style=discord.TextStyle.paragraph,
            default=existing or None,
            max_length=1500,
            required=True,
        )
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            result = process_submission(db.active_cohort(), interaction.user, self.answer.value, self.day)
        except SubmitError as e:
            await private(interaction, error_embed(str(e)))
            return
        await private(interaction, submission_embed(result))

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"Submit modal алдаа: {error}")
        try:
            await private(interaction, error_embed("❌ Алдаа гарлаа. Дахин `/submit` хийнэ үү."))
        except discord.HTTPException:
            pass


@client.tree.command(name="submit", description="Өнөөдрийн даалгаврын хариуг илгээх (өдөрт нэг удаа, засаж болно)")
@app_commands.guild_only()
async def submit(interaction: discord.Interaction):
    cohort = db.active_cohort()
    day = logic.cohort_day(cohort["start_date"]) if cohort else 0
    if not cohort or cohort["status"] != "running" or not 1 <= day <= cohort["days"]:
        await private(interaction, info_embed("Одоогоор илгээх өдөр алга."))
        return
    cid = cohort["cohort_id"]
    if not db.is_enrolled(cid, interaction.user.id):
        await private(interaction, info_embed("Эхлээд `/join` гэж бичиж cohort-д бүртгүүлнэ үү."))
        return
    existing = db.get_submission(cid, interaction.user.id, day)
    await interaction.response.send_modal(SubmitModal(cohort, day, existing["body"] if existing else ""))


# ----------------------
# Хаагдсан өдрийн илгээлтүүдийг forum-д нийтлэх, bonus олгох, сануулга
# ----------------------
def award_perfect_weeks(cohort, day):
    """Дууссан долоо хоног бүрт 7/7 илгээсэн хүнд bonus. Давхар олгохгүй."""
    cid = cohort["cohort_id"]
    last_closed = min(day - 1, cohort["days"])
    for week in range(1, last_closed // 7 + 1):
        first, last = (week - 1) * 7 + 1, week * 7
        source = f"perfect_week_{week}"
        for uid in db.perfect_week_users(cid, first, last):
            if not db.has_event(uid, cid, source):
                db.add_exp(uid, source, config.EXP_PERFECT_WEEK, cohort_id=cid)


async def publish_pending(cohort):
    """Өчигдрийн (болон өмнөх) илгээлтүүдийг forum-д пост болгоно. Амжаагүйг дараагийн минутад үргэлжлүүлнэ."""
    forum = await get_channel_by_state("submissions_forum_id")
    if forum is None:
        return
    if not isinstance(forum, discord.ForumChannel):
        print("submissions_forum тохиргоо forum суваг биш байна (/admin setup)")
        return

    day = logic.cohort_day(cohort["start_date"])
    for row in db.pending_publication(cohort["cohort_id"], day, limit=15):
        user = db.get_user(row["user_id"])
        anon = bool(user and user["anonymous"])
        name = "Anonymous" if anon else ((user and user["display_name"]) or "Суралцагч")
        embed = discord.Embed(description=row["body"], color=GOLD)
        icon = None if anon or not user else user["avatar_url"]
        embed.set_author(name=name, icon_url=icon)
        embed.set_footer(text=f"Өдөр {row['day']} • {row['word_count']} үг")
        try:
            created = await forum.create_thread(name=f"Өдөр {row['day']} — {name}"[:100], embed=embed)
            db.set_post_id(row["id"], created.thread.id)
        except discord.HTTPException as e:
            print(f"Forum пост үүсгэж чадсангүй: {e}")
            return
        await asyncio.sleep(1.2)


async def reminder_tick(cohort):
    if cohort["status"] != "running":
        return
    now = logic.now_ub()
    day = logic.cohort_day(cohort["start_date"], now)
    if not 1 <= day <= cohort["days"] or now.hour < config.REMINDER_HOUR:
        return
    key = logic.day_key(now).isoformat()
    if db.state_get("last_reminder") == key:
        return
    db.state_set("last_reminder", key)

    missing = db.count_not_submitted(cohort["cohort_id"], day)
    if missing <= 0:
        return
    channel = await get_channel_by_state("today_channel_id")
    if channel is None:
        return
    deadline = logic.day_deadline(cohort["start_date"], day)
    text = f"⏰ {missing} хүн өнөөдрийн даалгавраа илгээгээгүй байна. Үлдсэн хугацаа: {ts(deadline, 'R')}"
    try:
        await channel.send(embed=info_embed(text, color=GOLD), delete_after=3 * 3600)
    except discord.HTTPException:
        pass


# ----------------------
# Cohort leaderboard
# ----------------------
def board_embeds(cohort, rows):
    if not rows:
        return [info_embed("Одоогоор оноо авсан хүн алга. Эхний хүн чи бай!", title="🏆 Cohort leaderboard", color=GOLD)]
    embeds = []
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    total = max(cohort["days"], 1)
    for i, r in enumerate(rows, 1):
        anon = bool(r["anonymous"])
        name = "Anonymous" if anon else (r["display_name"] or "Суралцагч")
        filled = min(r["days_done"] * 10 // total, 10)
        e = discord.Embed(
            description=f"**{r['exp']} оноо** · {r['days_done']}/{total} өдөр\n{'▰' * filled}{'▱' * (10 - filled)}",
            color=GOLD if i <= 3 else discord.Color.dark_grey(),
        )
        e.set_author(name=f"{medals.get(i, f'{i}.')} {name}", icon_url=None if anon else r["avatar_url"])
        embeds.append(e)
    return embeds


async def update_board(channel_key, msg_key, content, embeds):
    channel = await get_channel_by_state(channel_key)
    if channel is None:
        return
    msg = None
    msg_id = db.state_get(msg_key)
    if msg_id:
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(content=content, embeds=embeds)
        except discord.NotFound:
            msg = None
    if msg is None:
        msg = await channel.send(content=content, embeds=embeds)
        db.state_set(msg_key, msg.id)
        try:
            await msg.pin()
        except discord.HTTPException:
            pass


async def refresh_boards(force=False, final=False):
    cohort = db.active_cohort()
    if not cohort or cohort["status"] not in ("running", "finished"):
        return
    rows = db.cohort_board(cohort["cohort_id"], limit=10)
    day = min(max(logic.cohort_day(cohort["start_date"]), 1), cohort["days"])
    sig = repr([tuple(r) for r in rows]) + f"|{day}|{db.state_get('leaderboard_public_id')}|{db.state_get('leaderboard_private_id')}"
    if not force and db.state_get("lb_sig") == sig:
        return
    stamp = int(logic.now_ub().timestamp())
    content = (
        f"🏆 **{cohort['name']}** — Өдөр {day}/{cohort['days']}{' · эцсийн дүн' if final else ''}\n"
        f"Сүүлд шинэчилсэн: <t:{stamp}:R>"
    )
    embeds = board_embeds(cohort, rows)
    await update_board("leaderboard_public_id", "lb_msg_public", content, embeds)
    await update_board("leaderboard_private_id", "lb_msg_private", content, embeds)
    db.state_set("lb_sig", sig)


@tasks.loop(minutes=config.LEADERBOARD_REFRESH_MINUTES)
async def leaderboard_loop():
    try:
        await refresh_boards()
    except Exception as e:
        print(f"Leaderboard алдаа: {e}")


@leaderboard_loop.before_loop
async def _before_leaderboard():
    await client.wait_until_ready()


@client.tree.command(name="rank", description="Cohort дахь байр, оноо, ахицаа харах")
@app_commands.guild_only()
async def rank(interaction: discord.Interaction):
    cohort = db.active_cohort()
    if not cohort or cohort["status"] not in ("running", "finished"):
        await private(interaction, info_embed("Cohort одоогоор явагдахгүй байна."))
        return
    cid = cohort["cohort_id"]
    uid = interaction.user.id
    if not db.is_enrolled(cid, uid):
        await private(interaction, info_embed("Эхлээд `/join` гэж бичиж cohort-д бүртгүүлнэ үү."))
        return

    total = cohort["days"]
    day = logic.cohort_day(cohort["start_date"])
    done = db.submitted_days(cid, uid)
    ranking = db.cohort_board(cid)
    pos = next((i for i, r in enumerate(ranking, 1) if r["user_id"] == str(uid)), None)
    streak = logic.streak_length(done, day if day in done else day - 1)
    lines = [
        f"**Байр:** {pos}/{len(ranking)}" if pos else "**Байр:** одоохондоо жагсаалтад ороогүй",
        f"**Оноо:** {db.total_exp(uid, cid)}",
        f"**Илгээсэн:** {len(done)}/{total} өдөр",
        f"**Streak:** 🔥 {streak}",
    ]
    embed = info_embed("\n".join(lines), title="📈 Миний ахиц", color=GOLD)
    embed.add_field(name="Өдрүүд", value=logic.progress_track(total, done, day), inline=False)
    embed.set_footer(text="🟩 илгээсэн • ⬛ алгассан • ⬜ ирээгүй")
    await private(interaction, embed)


# ----------------------
# Хариултын түлхүүр, жишээ хариуг embed-д нэмэх (submit болон library хоёуланд)
# ----------------------
def add_key_fields(embed, pday):
    if pday.get("answer_key"):
        lines = [f"**{i}.** {a}"[:900] for i, a in enumerate(pday["answer_key"], 1)]
        for n, chunk in enumerate(logic.chunk_lines(lines, 1000)):
            embed.add_field(
                name="Асуултуудын хариу" if n == 0 else "Асуултуудын хариу (үргэлжлэл)",
                value=chunk,
                inline=False,
            )
    if pday.get("model_reply"):
        embed.add_field(name="Жишээ хариу", value=pday["model_reply"][:1000], inline=False)
    if pday.get("model_notes"):
        embed.add_field(name="Яагаад сайн вэ", value=pday["model_notes"][:1000], inline=False)


# ----------------------
# Library
# ----------------------
class LibraryError(Exception):
    """Хэрэглэгчид шууд харуулах алдаа."""


def library_programs():
    try:
        return json.loads(db.state_get("library_programs") or "[]")
    except json.JSONDecodeError:
        return []


def library_set_program(program_id, enabled):
    items = [p for p in library_programs() if p != program_id]
    if enabled:
        items.append(program_id)
    db.state_set("library_programs", json.dumps(items))


def library_url(program_id, day):
    p = programs.get(program_id)
    if not p:
        return None
    return f"{p.get('library_pages_url') or p['pages_url']}?day={day}"


def library_open_embed(program_id, day):
    p = programs[program_id]
    title = private_day({"program_id": program_id}, day).get("title")
    head = f"📚 {p['title']} — Өдөр {day}/{p['days']}" + (f": {title}" if title else "")
    text = (
        f"[Өнөөдрийн хуудас руу орох]({library_url(program_id, day)})\n\n"
        "Даалгавраа дэвтэр дээрээ бичээд хийнэ. Дуусмагц доорх **Дуусгалаа** товчийг дарна: "
        "хариултын түлхүүр болон жишээ хариу гарна. Дараагийн хуудас маргааш 06:00 (UB) цагт нээгдэнэ."
    )
    return discord.Embed(title=head, description=text, color=GOLD)


def library_finish(user_id, program_id, day):
    """Хуудсыг дуусгаж, түлхүүрийг нээнэ. Буруу бол LibraryError."""
    p = programs.get(program_id)
    enr = db.library_get(user_id, program_id)
    if not p or not enr:
        raise LibraryError("Эхлээд `/library start` хийнэ үү.")
    state, _ = logic.library_state(enr["current_day"], enr["next_unlock_at"], p["days"])
    if state != "open" or enr["current_day"] != day:
        raise LibraryError("Энэ хуудас нээлттэй биш эсвэл аль хэдийн дууссан байна.")
    unlock = logic.next_unlock()
    if not db.library_complete_day(user_id, program_id, day, unlock.isoformat()):
        raise LibraryError("Энэ хуудас аль хэдийн дууссан байна.")

    embed = discord.Embed(title=f"✅ Өдөр {day} дууслаа", color=discord.Color.green())
    if day >= p["days"]:
        embed.description = "🎉 Бүх хуудсыг дуусгалаа! Баяр хүргэе."
    else:
        embed.description = f"Дараагийн хуудас {ts(unlock, 'R')} нээгдэнэ."
    add_key_fields(embed, private_day({"program_id": program_id}, day))
    return embed


class LibraryDoneView(discord.ui.View):
    def __init__(self, user_id, program_id, day):
        super().__init__(timeout=900)
        self.user_id, self.program_id, self.day = user_id, program_id, day

    @discord.ui.button(label="Дуусгалаа", style=discord.ButtonStyle.success, emoji="✅")
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Энэ товч чинийх биш.", ephemeral=True)
            return
        try:
            embed = library_finish(self.user_id, self.program_id, self.day)
        except LibraryError as e:
            await interaction.response.edit_message(embed=error_embed(str(e)), view=None)
            return
        self.stop()
        await interaction.response.edit_message(embed=embed, view=None)


def pick_library_program(user_id, program):
    """Хэрэглэгчийн library хөтөлбөрийг сонгоно: нэг л бол автоматаар."""
    mine = [r["program_id"] for r in db.library_list(user_id)]
    if program:
        if program not in mine:
            raise LibraryError("Та энэ хөтөлбөрийг эхлээгүй байна. `/library start` ашиглана уу.")
        return program
    if not mine:
        raise LibraryError("Та library-д хөтөлбөр эхлээгүй байна. `/library start` ашиглана уу.")
    if len(mine) > 1:
        raise LibraryError("Хэд хэдэн хөтөлбөр эхэлсэн байна. `program` талбарт сонгоно уу.")
    return mine[0]


library = app_commands.Group(name="library", description="Өөрийн хурдаар суралцах сан", guild_only=True)
client.tree.add_command(library)


async def _my_programs_autocomplete(interaction: discord.Interaction, current: str):
    ids = [r["program_id"] for r in db.library_list(interaction.user.id)]
    return [
        app_commands.Choice(name=programs[p]["title"][:100], value=p)
        for p in ids if p in programs and current.lower() in programs[p]["title"].lower()
    ][:25]


@library.command(name="start", description="Library-аас хөтөлбөр сонгож эхлэх")
@app_commands.describe(program="Хөтөлбөр")
async def library_start_cmd(interaction: discord.Interaction, program: str):
    if program not in library_programs() or program not in programs:
        await private(interaction, error_embed("Ийм хөтөлбөр library-д алга."))
        return
    if db.library_get(interaction.user.id, program):
        await private(interaction, info_embed("Та энэ хөтөлбөрийг аль хэдийн эхэлсэн. `/library today` гэж бичнэ үү."))
        return
    db.ensure_user(interaction.user.id, interaction.user.display_name, interaction.user.display_avatar.url)
    db.library_start(interaction.user.id, program)
    await private(interaction, info_embed(
        f"**{programs[program]['title']}** эхэллээ. `/library today` гэж бичээд эхний хуудсаа үзээрэй.",
        title="📚 Library", color=GOLD,
    ))


@library_start_cmd.autocomplete("program")
async def _library_start_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=programs[p]["title"][:100], value=p)
        for p in library_programs() if p in programs and current.lower() in programs[p]["title"].lower()
    ][:25]


@library.command(name="today", description="Library-н өнөөдрийн хуудас")
@app_commands.describe(program="Хөтөлбөр (нэгийг л эхэлсэн бол шаардлагагүй)")
async def library_today_cmd(interaction: discord.Interaction, program: Optional[str] = None):
    try:
        pid = pick_library_program(interaction.user.id, program)
    except LibraryError as e:
        await private(interaction, info_embed(str(e)))
        return
    p = programs.get(pid)
    if not p:
        await private(interaction, error_embed("Хөтөлбөр олдсонгүй."))
        return
    enr = db.library_get(interaction.user.id, pid)
    state, unlock = logic.library_state(enr["current_day"], enr["next_unlock_at"], p["days"])
    if state == "finished":
        await private(interaction, info_embed("Та бүх хуудсыг дуусгасан. Хариултыг `/library answers` -аар дахин үзнэ."))
    elif state == "locked":
        await private(interaction, info_embed(f"Өнөөдрийн хуудсаа дуусгасан. Дараагийн хуудас {ts(unlock, 'R')} нээгдэнэ."))
    else:
        day = enr["current_day"]
        view = LibraryDoneView(interaction.user.id, pid, day)
        await interaction.response.send_message(embed=library_open_embed(pid, day), view=view, ephemeral=True)


@library_today_cmd.autocomplete("program")
async def _library_today_autocomplete(interaction: discord.Interaction, current: str):
    return await _my_programs_autocomplete(interaction, current)


@library.command(name="answers", description="Дуусгасан өдрийн хариултын түлхүүрийг дахин үзэх")
@app_commands.describe(day="Дуусгасан өдөр", program="Хөтөлбөр (нэгийг л эхэлсэн бол шаардлагагүй)")
async def library_answers_cmd(interaction: discord.Interaction, day: int, program: Optional[str] = None):
    try:
        pid = pick_library_program(interaction.user.id, program)
    except LibraryError as e:
        await private(interaction, info_embed(str(e)))
        return
    if day not in db.library_done_days(interaction.user.id, pid):
        await private(interaction, info_embed("Эхлээд тухайн хуудсыг дуусгах хэрэгтэй."))
        return
    embed = discord.Embed(title=f"🔑 Өдөр {day} — хариулт", color=GOLD)
    add_key_fields(embed, private_day({"program_id": pid}, day))
    await private(interaction, embed)


@library_answers_cmd.autocomplete("program")
async def _library_answers_autocomplete(interaction: discord.Interaction, current: str):
    return await _my_programs_autocomplete(interaction, current)


# ----------------------
# Cohort хаах
# ----------------------
def compute_final(cohort):
    """(board, graduates, awards). awards = [(user_id, source, amount)] main board руу."""
    cid = cohort["cohort_id"]
    board = db.cohort_board(cid)
    need = logic.graduate_min_days(cohort["days"])
    graduates = [r for r in board if r["days_done"] >= need]
    awards = []

    for rank, r in enumerate(graduates, 1):
        awards.append((r["user_id"], f"cohort_graduate_{cid}", config.BONUS_GRADUATE))
        if rank <= 3:
            awards.append((r["user_id"], f"cohort_place_{cid}", config.BONUS_TOP3))
        elif rank <= 10:
            awards.append((r["user_id"], f"cohort_place_{cid}", config.BONUS_TOP10))
    return board, graduates, awards


def apply_awards(awards):
    """Main board руу bonus олгоно. Давхар олгохгүй. Олгосон тоог буцаана."""
    given = 0
    for uid, source, amount in awards:
        if not db.has_main_event(uid, source):
            db.add_exp(uid, source, amount)
            given += 1
    return given


def final_embed(cohort, board, graduates):
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = []
    for i, r in enumerate(board[:10], 1):
        who = "Anonymous" if r["anonymous"] else f"<@{r['user_id']}>"
        lines.append(f"{medals.get(i, f'`{i}.`')} {who} — **{r['exp']}** оноо · {r['days_done']}/{cohort['days']} өдөр")
    embed = discord.Embed(
        title=f"🎓 {cohort['name']} — эцсийн дүн",
        description="\n".join(lines) or "—",
        color=GOLD,
    )
    need = logic.graduate_min_days(cohort["days"])
    embed.add_field(name="Төгссөн", value=f"{len(graduates)} хүн (хамгийн багадаа {need} өдөр)")
    embed.set_footer(text="Хөтөлбөр одоо library-д нээлттэй: /library start")
    return embed


def close_preview(cohort):
    board, graduates, awards = compute_final(cohort)
    need = logic.graduate_min_days(cohort["days"])
    total = sum(a for _, _, a in awards)
    lines = [
        f"**Оролцогч:** {len(board)}",
        f"**Төгсөх хүн:** {len(graduates)} (хамгийн багадаа {need} өдөр)",
        f"**Main board руу өгөх bonus:** {len(awards)} мөр, нийт {total} EXP",
        "",
        "Хаахад: bonus олгоно, Graduate role өгнө, эцсийн дүнг зарлана, хөтөлбөрийг library-д нээнэ, leaderboard-ыг хөлдөөнө.",
        "Үргэлжлүүлэх бол `/admin close confirm:True` гэж бичнэ.",
    ]
    return info_embed("\n".join(lines), title="🎓 Cohort хаах (урьдчилсан харагдац)", color=GOLD)


async def run_close(cohort, guild):
    cid = cohort["cohort_id"]
    board, graduates, awards = compute_final(cohort)
    given = apply_awards(awards)

    role_id = db.state_get("graduate_role_id")
    role = guild.get_role(int(role_id)) if role_id else None
    role_given = 0
    if role:
        for r in graduates:
            try:
                member = await guild.fetch_member(int(r["user_id"]))
                await member.add_roles(role, reason=f"Cohort {cid} graduate")
                role_given += 1
            except discord.HTTPException as e:
                print(f"Graduate role өгч чадсангүй ({r['user_id']}): {e}")

    await refresh_boards(force=True, final=True)
    library_set_program(cohort["program_id"], True)
    db.set_cohort_status(cid, "closed")
    for key in ("lb_sig", "lb_msg_public", "lb_msg_private", "today_message_id", "last_reminder"):
        db.state_delete(key)

    embed = final_embed(cohort, board, graduates)
    for key in ("today_channel_id", "leaderboard_public_id"):
        channel = await get_channel_by_state(key)
        if channel is not None:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException as e:
                print(f"Эцсийн дүн илгээж чадсангүй: {e}")
    return {"participants": len(board), "graduates": len(graduates), "awards": given, "roles": role_given}


# ----------------------
# /admin командууд
# ----------------------
admin = app_commands.Group(
    name="admin",
    description="Админ командууд",
    default_permissions=discord.Permissions(administrator=True),
    guild_only=True,
)
client.tree.add_command(admin)


def _mention_state(key, kind):
    value = db.state_get(key)
    if not value:
        return "—"
    return f"<#{value}>" if kind == "channel" else f"<@&{value}>"


@admin.command(name="setup", description="Суваг болон role-уудыг тохируулах (өгсөн зүйлийг л шинэчилнэ)")
@app_commands.describe(
    today_channel="Өдрийн хуудас гарах суваг (зөвхөн уншигдана)",
    cohort_role="Cohort-д орсон хүмүүст өгөх role",
    submissions_forum="Илгээлтүүд гарах forum суваг",
    graduate_role="Cohort дуусгасан хүмүүст өгөх role",
    leaderboard_public="Нийтийн leaderboard суваг",
    leaderboard_private="Cohort дотоод leaderboard суваг",
)
@app_commands.checks.has_permissions(administrator=True)
async def admin_setup(
    interaction: discord.Interaction,
    today_channel: Optional[discord.TextChannel] = None,
    cohort_role: Optional[discord.Role] = None,
    submissions_forum: Optional[discord.ForumChannel] = None,
    graduate_role: Optional[discord.Role] = None,
    leaderboard_public: Optional[discord.TextChannel] = None,
    leaderboard_private: Optional[discord.TextChannel] = None,
):
    updates = {
        "today_channel_id": today_channel,
        "cohort_role_id": cohort_role,
        "submissions_forum_id": submissions_forum,
        "graduate_role_id": graduate_role,
        "leaderboard_public_id": leaderboard_public,
        "leaderboard_private_id": leaderboard_private,
    }
    for key, obj in updates.items():
        if obj is not None:
            db.state_set(key, obj.id)
    db.state_set("admin_id", interaction.user.id)

    text = (
        f"**Today суваг:** {_mention_state('today_channel_id', 'channel')}\n"
        f"**Cohort role:** {_mention_state('cohort_role_id', 'role')}\n"
        f"**Submissions forum:** {_mention_state('submissions_forum_id', 'channel')}\n"
        f"**Graduate role:** {_mention_state('graduate_role_id', 'role')}\n"
        f"**Leaderboard (нийтийн):** {_mention_state('leaderboard_public_id', 'channel')}\n"
        f"**Leaderboard (дотоод):** {_mention_state('leaderboard_private_id', 'channel')}"
    )
    await private(interaction, info_embed(text, title="⚙️ Тохиргоо"))


@admin.command(name="cohort_create", description="Шинэ cohort үүсгэх")
@app_commands.describe(
    cohort_id="Богино ID, жишээ: c1",
    name="Нэр, жишээ: Cohort 1",
    start_date="Эхлэх өдөр YYYY-MM-DD (06:00 UB цагт эхэлнэ)",
    program="programs.json дахь ID",
    days="Өдрийн тоо",
    min_seats="Хамгийн цөөн хүн",
    max_seats="Хамгийн олон хүн",
)
@app_commands.checks.has_permissions(administrator=True)
async def admin_cohort_create(
    interaction: discord.Interaction,
    cohort_id: str,
    name: str,
    start_date: str,
    program: str = "english-a2b1",
    days: int = config.DEFAULT_DAYS,
    min_seats: int = config.DEFAULT_MIN_SEATS,
    max_seats: int = config.DEFAULT_MAX_SEATS,
):
    try:
        start = date.fromisoformat(start_date)
    except ValueError:
        await private(interaction, error_embed("Огноо буруу. YYYY-MM-DD хэлбэрээр бичнэ үү."))
        return
    if start < logic.day_key():
        await private(interaction, error_embed("Эхлэх өдөр өнгөрсөн байна."))
        return
    if program not in programs:
        await private(interaction, error_embed(f"Ийм program алга. Боломжит: {', '.join(programs) or '—'}"))
        return
    if not 1 <= min_seats <= max_seats:
        await private(interaction, error_embed("Суудлын тоо буруу байна."))
        return
    try:
        db.create_cohort(cohort_id, name, program, start.isoformat(), days, min_seats, max_seats, config.JOIN_CUTOFF_DAY)
    except ValueError as e:
        await private(interaction, error_embed(str(e)))
        return
    db.state_set("admin_id", interaction.user.id)
    await private(interaction, info_embed(
        f"**{name}** үүслээ. Эхлэх: **{start_date} 06:00 (UB)**, {min_seats}–{max_seats} суудал.",
        title="✅ Cohort үүслээ",
    ))


@admin.command(name="cohort_postpone", description="Эхлээгүй cohort-ийн эхлэх өдрийг өөрчлөх")
@app_commands.describe(new_start_date="Шинэ эхлэх өдөр YYYY-MM-DD")
@app_commands.checks.has_permissions(administrator=True)
async def admin_cohort_postpone(interaction: discord.Interaction, new_start_date: str):
    cohort = db.active_cohort()
    if not cohort or cohort["status"] != "scheduled":
        await private(interaction, error_embed("Хойшлуулах cohort алга (зөвхөн эхлээгүй cohort-ийг хойшлуулна)."))
        return
    try:
        start = date.fromisoformat(new_start_date)
    except ValueError:
        await private(interaction, error_embed("Огноо буруу. YYYY-MM-DD хэлбэрээр бичнэ үү."))
        return
    if start < logic.day_key():
        await private(interaction, error_embed("Эхлэх өдөр өнгөрсөн байна."))
        return
    db.set_cohort_start(cohort["cohort_id"], start.isoformat())
    await private(interaction, info_embed(f"Шинэ эхлэх өдөр: **{new_start_date} 06:00 (UB)**. Бүртгүүлсэн хүмүүст зарлахаа бүү март."))


@admin.command(name="cohort_status", description="Cohort-ийн одоогийн байдал")
@app_commands.checks.has_permissions(administrator=True)
async def admin_cohort_status(interaction: discord.Interaction):
    cohort = db.active_cohort()
    if not cohort:
        await private(interaction, info_embed("Идэвхтэй cohort алга."))
        return
    cid = cohort["cohort_id"]
    day = logic.cohort_day(cohort["start_date"])
    lines = [
        f"**Нэр:** {cohort['name']} (`{cid}`)",
        f"**Төлөв:** {cohort['status']}",
        f"**Эхлэх өдөр:** {cohort['start_date']}",
        f"**Өнөөдрийн өдөр:** {day if day >= 1 else 'эхлээгүй'}",
        f"**Бүртгэлтэй:** {db.count_enrolled(cid)} (доод {cohort['min_seats']}, дээд {cohort['max_seats']})",
    ]
    if 1 <= day <= cohort["days"]:
        lines.append(f"**Өнөөдрийн илгээлт:** {db.count_submissions(cid, day)}")
    await private(interaction, info_embed("\n".join(lines), title="📊 Cohort"))


@admin.command(name="repost_day", description="#today мессежийг одоогийн өдрөөр дахин засах")
@app_commands.checks.has_permissions(administrator=True)
async def admin_repost_day(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    cohort = db.active_cohort()
    day = logic.cohort_day(cohort["start_date"]) if cohort else 0
    if not cohort or cohort["status"] != "running" or not 1 <= day <= cohort["days"]:
        await private(interaction, error_embed("Одоо явагдаж буй өдөр алга."))
        return
    ok = await post_today(cohort, day, ping=False)
    await private(interaction, info_embed("Шинэчлэгдлээ." if ok else "Today суваг тохируулаагүй байна."))


@admin.command(name="feature", description="Илгээлтийг онцлох (+EXP)")
@app_commands.describe(user="Хэний илгээлт", day="Аль өдрийн илгээлт")
@app_commands.checks.has_permissions(administrator=True)
async def admin_feature(interaction: discord.Interaction, user: discord.Member, day: int):
    await interaction.response.defer(ephemeral=True)
    cohort = db.active_cohort()
    sub = db.get_submission(cohort["cohort_id"], user.id, day) if cohort else None
    if not sub:
        await private(interaction, error_embed("Ийм илгээлт олдсонгүй."))
        return
    cid = cohort["cohort_id"]
    source = f"featured_{day}"
    if db.has_event(user.id, cid, source):
        await private(interaction, error_embed("Энэ илгээлтийг аль хэдийн онцолсон."))
        return
    db.add_exp(user.id, source, config.EXP_FEATURED, cohort_id=cid)

    posted = False
    if sub["post_id"]:
        try:
            thread = client.get_channel(int(sub["post_id"])) or await client.fetch_channel(int(sub["post_id"]))
            await thread.send(embed=info_embed(f"⭐ Онцолсон хариу! +{config.EXP_FEATURED} оноо", color=GOLD))
            posted = True
        except discord.HTTPException:
            pass
    note = "Пост дээр тэмдэглэв." if posted else "Пост олдоогүй эсвэл хараахан нийтлэгдээгүй байна."
    await private(interaction, info_embed(f"{user.display_name}: +{config.EXP_FEATURED} оноо. {note}"))


@admin.command(name="grant", description="Гараар EXP нэмэх эсвэл хасах")
@app_commands.describe(
    user="Хэнд",
    amount="Нэмэх тоо (хасах бол сөрөг тоо)",
    board="cohort эсвэл main",
    reason="Шалтгаан",
)
@app_commands.checks.has_permissions(administrator=True)
async def admin_grant(
    interaction: discord.Interaction,
    user: discord.Member,
    amount: int,
    board: Literal["cohort", "main"] = "cohort",
    reason: str = "admin",
):
    if amount == 0 or abs(amount) > 10000:
        await private(interaction, error_embed("Тоо буруу байна (0 биш, 10000-аас бага)."))
        return
    cid = None
    if board == "cohort":
        cohort = db.active_cohort()
        if not cohort:
            await private(interaction, error_embed("Идэвхтэй cohort алга."))
            return
        cid = cohort["cohort_id"]
    db.ensure_user(user.id, user.display_name, user.display_avatar.url)
    db.add_exp(user.id, f"admin: {reason}"[:60], amount, cohort_id=cid)
    await private(interaction, info_embed(f"{user.display_name}: {amount:+d} EXP ({board})."))


@admin.command(name="close", description="Cohort-ийг хааж, эцсийн дүн гаргах")
@app_commands.describe(
    confirm="True бол бодитоор хаана. Үгүй бол урьдчилж харуулна",
    force="Дуусаагүй cohort-ийг хаах",
)
@app_commands.checks.has_permissions(administrator=True)
async def admin_close(interaction: discord.Interaction, confirm: bool = False, force: bool = False):
    await interaction.response.defer(ephemeral=True)
    cohort = db.active_cohort()
    if not cohort:
        await private(interaction, error_embed("Хаах cohort алга."))
        return
    if cohort["status"] != "finished" and not force:
        await private(interaction, error_embed(
            f"Cohort одоогоор `{cohort['status']}` төлөвтэй. Дуусах хүртэл хүлээнэ үү, эсвэл `force:True` ашиглана."
        ))
        return
    if not confirm:
        await private(interaction, close_preview(cohort))
        return
    summary = await run_close(cohort, interaction.guild)
    await private(interaction, info_embed(
        f"Оролцогч: {summary['participants']}\nТөгссөн: {summary['graduates']}\n"
        f"Bonus олгосон: {summary['awards']} мөр\nGraduate role өгсөн: {summary['roles']}\n"
        "Хөтөлбөр library-д нээгдлээ.",
        title="✅ Cohort хаагдлаа",
    ))


@admin.command(name="library_set", description="Хөтөлбөрийг library-д нээх / хаах")
@app_commands.describe(program="programs.json дахь ID", enabled="True = нээх, False = хаах")
@app_commands.checks.has_permissions(administrator=True)
async def admin_library_set(interaction: discord.Interaction, program: str, enabled: bool = True):
    if program not in programs:
        await private(interaction, error_embed(f"Ийм program алга. Боломжит: {', '.join(programs) or '—'}"))
        return
    library_set_program(program, enabled)
    await private(interaction, info_embed(f"`{program}` library-д {'нээгдлээ' if enabled else 'хаагдлаа'}."))


# ----------------------
# Slash алдаа
# ----------------------
@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        embed = error_embed("Энэ команд зөвхөн админд зориулагдсан.")
    else:
        print(f"Slash error: {error}")
        embed = error_embed("❌ Алдаа гарлаа. Дараа дахин оролдоорой.")
    try:
        await private(interaction, embed)
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("TOKEN .env файлд алга байна")
    client.run(TOKEN)
