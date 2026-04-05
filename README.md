# Personal AI Agent

A personal automation agent controlled via Telegram. It posts on LinkedIn,
manages your Gmail, researches topics, and runs scheduled tasks — all from
a single chat interface.

---

## Architecture

```
You (Telegram) → Agent Brain (LangGraph + DeepSeek) → Tools
                                                     ├── LinkedIn (Playwright)
                                                     ├── Gmail (Google API)
                                                     ├── Deep Search (Tavily)
                                                     └── Google Sheets (log)
                           ↓
                     SQLite Memory + Scheduler
```

---

## Quick Start (Local Development)

### Step 1 — Clone and create virtual environment

```bash
git clone <your-repo-url>
cd personal-ai-agent

python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium        # Install headless browser for LinkedIn/screenshots
```

### Step 2 — Create your Telegram bot

1. Open Telegram → search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** (looks like `123456789:ABCdef...`)
4. Send a message to your bot, then visit:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
5. Find your **chat ID** in the response (the `id` inside `from`)

### Step 3 — Get API keys

| Service | Where to get it | Used for |
|---------|----------------|---------|
| **DeepSeek** | [platform.deepseek.com](https://platform.deepseek.com) | Primary LLM (cheap, fast) |
| **OpenAI** | [platform.openai.com](https://platform.openai.com) | GPT-4o fallback |
| **Tavily** | [tavily.com](https://tavily.com) | Web search |
| **Gmail** | Google Cloud Console → Gmail API | Email |
| **Google Sheets** | Same Google Cloud credentials | Activity log |

### Step 4 — Configure Gmail (OAuth2)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project → Enable **Gmail API** and **Google Sheets API**
3. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
4. Choose **Desktop App** → Download JSON → Save as `secrets/gmail_credentials.json`
5. First time you run the app, a browser window will open asking you to authorize

### Step 5 — Get LinkedIn li_at cookie

1. Log in to LinkedIn in Chrome
2. Open DevTools (F12) → Application tab → Cookies → linkedin.com
3. Find the cookie named `li_at` — copy its value
4. Paste into `.env` as `LINKEDIN_LI_AT_COOKIE`

> ⚠️ This cookie expires periodically. When posting stops working, refresh it.

### Step 6 — Set up environment

```bash
cp .env.example .env
# Now edit .env with your actual keys
nano .env    # or use any text editor
```

Minimum required fields:
```env
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_ALLOWED_USERS=your_telegram_user_id
DEEPSEEK_API_KEY=your_deepseek_key
OPENAI_API_KEY=your_openai_key
TAVILY_API_KEY=your_tavily_key
LINKEDIN_LI_AT_COOKIE=your_li_at_value
```

### Step 7 — Run

```bash
python main.py
```

You should see:
```
[INFO] database_initialized
[INFO] scheduler_started
[INFO] polling_mode_started
```

Now open Telegram, send `/start` to your bot, and type a task!

---

## Example Commands to Try

```
Post a LinkedIn post about the future of AI agents
```
```
Check my inbox and tell me what needs urgent attention
```
```
Research the latest trends in no-code automation tools
```
```
Send an email to john@example.com with subject "Meeting Tomorrow" 
saying we'll meet at 3pm
```
```
Screenshot https://openai.com
```
```
What have you done today? Show me activity history
```

---

## Telegram Bot Commands

| Command | What it does |
|---------|-------------|
| `/start` | Welcome message + capabilities |
| `/clear` | Clear conversation memory (fresh start) |
| `/history` | Show last 10 activities |

---

## Scheduled Automations

Edit `scheduler/jobs.py` to customize:

| Job | Schedule | What it does |
|-----|----------|-------------|
| `daily_linkedin_post` | 9:00 AM UTC | Auto-generates a LinkedIn post idea |
| `morning_email_digest` | 8:00 AM UTC | Summarizes your inbox |
| `weekly_summary` | Monday 7:00 AM UTC | Reports all agent activities |

To change the schedule, edit the `CronTrigger` parameters:
```python
# Every day at 10:30 AM
CronTrigger(hour=10, minute=30)

# Every Monday and Wednesday at 9 AM
CronTrigger(day_of_week="mon,wed", hour=9)

# Every hour
CronTrigger(minute=0)
```

---

## Production Deployment (Railway / Render / VPS)

### Option A: Railway (Easiest, ~$5/month)

```bash
npm install -g @railway/cli
railway login
railway init
railway up
```
Set all `.env` variables in Railway's dashboard under **Variables**.
Set `APP_ENV=production` and `TELEGRAM_WEBHOOK_URL=https://your-app.railway.app`.

### Option B: VPS (DigitalOcean / Linode)

```bash
# On your server:
git clone <your-repo>
cd personal-ai-agent
cp .env.example .env && nano .env

# Run with Docker
docker-compose up -d

# View logs
docker-compose logs -f
```

You'll need a domain + SSL certificate for webhook mode.
Use [Caddy](https://caddyserver.com) — it handles HTTPS automatically:
```
your-domain.com {
    reverse_proxy localhost:8000
}
```

### Option C: Keep polling mode (simplest for personal use)

Just run `python main.py` on any machine — even your laptop.
Polling works fine for a personal agent with low traffic.

---

## Project Structure

```
personal-ai-agent/
├── main.py                    ← FastAPI app + Telegram bot (start here)
├── config.py                  ← All settings loaded from .env
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
│
├── agent/
│   ├── graph.py               ← LangGraph agent brain (core logic)
│   ├── state.py               ← What the agent "remembers" per turn
│   ├── prompts.py             ← System prompts (customize your agent's personality)
│   └── tools/
│       ├── linkedin.py        ← Post, draft LinkedIn content
│       ├── email_tool.py      ← Read, search, send Gmail
│       ├── deep_search.py     ← Tavily web search + screenshot
│       └── google_sheets.py   ← Activity log
│
├── memory/
│   └── store.py               ← SQLite memory (history, preferences, logs)
│
├── scheduler/
│   └── jobs.py                ← Scheduled automated tasks
│
├── utils/
│   ├── error_handler.py       ← Retry logic + error formatting
│   └── logger.py              ← Structured logging
│
├── secrets/                   ← Gmail OAuth credentials (gitignored)
├── data/                      ← SQLite database (gitignored)
└── screenshots/               ← Saved screenshots (gitignored)
```

---

## Adding a New Tool

1. Create `agent/tools/my_new_tool.py`:

```python
from langchain_core.tools import tool

@tool
async def my_new_tool(param: str) -> str:
    """
    Describe what this tool does so the LLM knows when to use it.
    
    Args:
        param: What this parameter is for.
    """
    # Your logic here
    return "result"
```

2. Register it in `agent/graph.py`:

```python
from agent.tools.my_new_tool import my_new_tool

ALL_TOOLS = [
    ...,
    my_new_tool,  # Add here
]
```

That's it. The LLM will automatically learn to use it from the docstring.

---

## Troubleshooting

**Bot not responding?**
- Check `TELEGRAM_BOT_TOKEN` is correct
- Check `TELEGRAM_ALLOWED_USERS` contains your user ID
- Run `python main.py` and watch the logs

**LinkedIn posting fails?**
- The `li_at` cookie may have expired — refresh it from your browser
- LinkedIn may have changed their page structure — check `screenshots/linkedin_error_*.png`

**Gmail not working?**
- Delete `secrets/gmail_token.json` and re-authorize
- Make sure Gmail API + Sheets API are enabled in Google Cloud Console

**DeepSeek errors?**
- Check your API key and account balance at platform.deepseek.com
- The agent will automatically fall back to OpenAI

---

## Cost Estimates

| Service | Cost |
|---------|------|
| DeepSeek API | ~$0.01-0.10/day for personal use |
| OpenAI fallback | ~$0-0.05/day (rarely used) |
| Tavily | Free tier: 1000 searches/month |
| Gmail + Sheets API | Free |
| Hosting (Railway) | ~$5/month |
| **Total** | **~$5-10/month** |

---

## Future Enhancements

- [ ] WhatsApp integration (via Twilio/WABA)
- [ ] Calendar integration (create/read Google Calendar events)
- [ ] Twitter/X posting
- [ ] Notion integration for notes and databases
- [ ] Voice message support (Whisper transcription)
- [ ] Multi-user support with per-user memory isolation
- [ ] Web UI dashboard (Next.js + FastAPI)
- [ ] RAG over your personal documents
- [ ] Agent memory with semantic search (replace SQLite with pgvector)
