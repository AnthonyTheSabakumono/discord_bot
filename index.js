const { Client, GatewayIntentBits } = require('discord.js');
const fs = require('fs');
const express = require('express');
const cors = require('cors');
const { ActionRowBuilder, ButtonBuilder, ButtonStyle, ComponentType } = require('discord.js');

// Load quiz
let quizData = [];
try {
    quizData = require('./english.json');
} catch {
    console.log("english.json not found");
}

const app = express();
const PORT = 3000;

// ----------------------
// Your Discord token
// ----------------------
const TOKEN = "MTQ3ODIzOTQxNjA2NDY3NTg4MA.G0bXCq.iqlh6XJgNETXyPZidLpplMLjkoufTVb_FO1se0";

// ----------------------
// Express Setup
// ----------------------
app.use(cors());
app.use(express.json());
app.use(express.static('web'));

app.listen(PORT, () => {
    console.log(`Web server running on port ${PORT}`);
});

// ----------------------
// Discord Client
// ----------------------
const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

// ----------------------
// Data System
// ----------------------
const DATA_FILE = './data.json';

function loadData() {
    if (!fs.existsSync(DATA_FILE)) return {};
    try {
        return JSON.parse(fs.readFileSync(DATA_FILE));
    } catch {
        return {};
    }
}

function saveData(data) {
    fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
}

function addExp(user, amount) {
    user.exp = (user.exp || 0) + amount;
    user.level = Math.floor(user.exp / 100) + 1;
}

// ----------------------
// Commands
// ----------------------
client.on('messageCreate', async (message) => {
    if (message.author.bot) return;

    const userId = message.author.id;
    const content = message.content.trim();
    const data = loadData();

    if (!data[userId]) data[userId] = {};
    const user = data[userId];

    // -------- !profile --------
    if (content === '!profile') {
        return message.reply(
            `👤 Profile\n\n⭐ Level: ${user.level || 1}\n⚡ EXP: ${user.exp || 0}\n🔥 Streak: ${user.checkinStreak || 0}`
        );
    }
    // -------- !test --------
    if (content.startsWith('!test')) {
        const args = content.split(' ');
        const testType = args[1] === 'japanese' ? 'japanese' : 'english';
        const TEST_URL = `https://akitothesabakumono.github.io/Test2/test.html?test=${testType}&userId=${userId}`;
        return message.reply(`Тестээ эндээс хийж болно:\n${TEST_URL}`);
    }

    // -------- !leaderboard --------
    if (content === '!leaderboard') {
        const sorted = Object.entries(data)
            .sort((a, b) => (b[1].exp || 0) - (a[1].exp || 0))
            .slice(0, 10);

        let text = '🏆 Leaderboard:\n';
        sorted.forEach(([id, u], i) => {
            text += `\n${i + 1}. <@${id}> - ${u.exp || 0} EXP`;
        });

        return message.reply(text);
    }

    // -------- !quiz --------
    if (content === '!quiz') {
    if (!quizData.length) return message.reply("❌ Quiz data алга байна");

    const now = new Date();
    const ubTime = new Date(
        now.toLocaleString("en-US", { timeZone: "Asia/Ulaanbaatar" })
    );
    const todayKey = ubTime.toISOString().slice(0, 10);

    user.quiz = user.quiz || { date: todayKey, count: 0 };
    if (user.quiz.date !== todayKey) user.quiz = { date: todayKey, count: 0 };

    if (user.quiz.count >= 3)
        return message.reply('⛔ Өнөөдрийн quiz лимит (3)');

    const q = quizData[Math.floor(Math.random() * quizData.length)];

    // Create buttons for options
    const row = new ActionRowBuilder();
    q.options.forEach((opt, i) => {
        row.addComponents(
            new ButtonBuilder()
                .setCustomId(`quiz_${i}_${userId}`) // unique per user
                .setLabel(opt)
                .setStyle(ButtonStyle.Primary)
        );
    });

    message.reply({ content: `❓ ${q.question}`, components: [row] });

    const filter = i => i.user.id === userId;

    // Button collector
    const collector = message.channel.createMessageComponentCollector({
        filter,
        max: 1,
        time: 15000, // 15 seconds
        componentType: ComponentType.Button
    });

    collector.on('collect', async i => {
        const [_, answerIndex, id] = i.customId.split('_');

        if (parseInt(answerIndex) === q.answer) {
            addExp(user, 20);
            await i.update({ content: `✅ Зөв! +20 EXP`, components: [] });
        } else {
            await i.update({ content: `❌ Буруу! Зөв: ${q.options[q.answer]}`, components: [] });
        }

        user.quiz.count++;
        saveData(data);
    });

    collector.on('end', collected => {
        if (collected.size === 0) {
            message.reply("⏰ Цаг дууслаа! Quiz дууссан.");
        }
    });
}

    // -------- !checkin --------
    if (content === '!checkin') {
        const now = new Date();
        const ubTime = new Date(
            now.toLocaleString("en-US", { timeZone: "Asia/Ulaanbaatar" })
        );

        if (ubTime.getHours() < 6) ubTime.setDate(ubTime.getDate() - 1);
        const todayKey = ubTime.toISOString().slice(0, 10);

        if (!user.lastCheckin) {
            user.lastCheckin = todayKey;
            user.checkinStreak = 1;
            addExp(user, 10);
            saveData(data);
            return message.reply(`🎉 Анхны check-in! +10 EXP`);
        }

        if (user.lastCheckin === todayKey) {
            return message.reply(`⏰ Аль хэдийн check-in хийсэн`);
        }

        const yesterday = new Date(ubTime);
        yesterday.setDate(yesterday.getDate() - 1);
        const yesterdayKey = yesterday.toISOString().slice(0, 10);

        user.checkinStreak =
            user.lastCheckin === yesterdayKey
                ? (user.checkinStreak || 0) + 1
                : 1;

        user.lastCheckin = todayKey;
        addExp(user, 10);

        saveData(data);

        return message.reply(`🎉 Check-in! Стрик: ${user.checkinStreak} (+10 EXP)`);
    }
});

// ----------------------
// Web API
// ----------------------
app.post('/submit-result', (req, res) => {
    const { userId, testType, score, level } = req.body;
    if (!userId) return res.status(400).json({ error: 'Missing data' });

    const data = loadData();
    if (!data[userId]) data[userId] = {};

    data[userId].tests = data[userId].tests || {};
    data[userId].tests[testType] = {
        score,
        level,
        date: new Date().toISOString()
    };

    saveData(data);
    return res.json({ success: true });
});

// ----------------------
client.once("ready", () => {
    console.log(`Logged in as ${client.user.tag}`);
});

client.login(TOKEN);