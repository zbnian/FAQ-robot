# Coffee FAQ Bot

A RAG (Retrieval-Augmented Generation) chatbot specialized in coffee knowledge.
Connects to Feishu (Lark) via WebSocket long-polling, retrieves answers from a local Markdown knowledge base, and generates strictly grounded responses through a local Ollama LLM — no hallucinations.

> English documentation · [中文 README](README.md)

---

## Features

- **Fully local RAG**: FAISS + `moka-ai/m3e-base` embeddings + local Ollama generation. No data leaves your network.
- **Anti-hallucination**: Strict prompt (cite-only, no embellishment) + `temperature=0.3` + similarity threshold `0.6`. Anything the KB cannot answer returns the literal string `暂无此信息` ("no information available").
- **Feishu integration**: lark-oapi WebSocket long connection. Replies in DMs directly; in group chats triggers on `@小光咖啡百科` (configurable).
- **Feedback loop**: Every "no information" answer is logged to `feedbacks/feedback_YYYYMMDD.jsonl` and pushed to the admin as an interactive Feishu card.
- **One-click marking**: Admin clicks `✓ Resolved` / `✗ Ignored` on the card; status updates in place (Chinese values: `待处理 / 已处理 / 已忽略`).
- **Admin commands**: DM the bot with `反馈列表 / 标记 <id> <status> [note] / 绑定管理员 / 帮助`.
- **Webhook fallback**: When WebSocket admin is unset, falls back to webhook (view-only, no buttons).

---

## Project Layout

```
FAQ机器人/
├── config/
│   └── settings.py          # pydantic-settings (reads .env)
├── src/
│   ├── indexer.py           # FAISS index builder
│   ├── retriever.py         # Vector retrieval + similarity filter
│   ├── generator.py         # Ollama client + strict prompt
│   ├── handler.py           # RAG orchestration + no-info detection
│   ├── feishu_client.py     # Feishu SDK wrapper (send / reply / card)
│   ├── feishu_ws.py         # Feishu WebSocket + command parser + card callback
│   ├── feedback.py          # Feedback collection / status marking / card builder
│   ├── notifier.py          # Notification dispatcher
│   ├── scheduler.py         # Scheduled jobs (e.g. index rebuild)
│   └── logger.py            # Logging
├── coffee/                  # Knowledge base (Markdown, mount or copy in)
├── data/                    # FAISS index persistence
├── feedbacks/               # Feedback jsonl (runtime)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── main.py
```

---

## Quick Start

### 1. Clone & configure

```bash
git clone <repo> faq-robot && cd faq-robot
cp .env.example .env
# Edit .env: fill in Feishu app_id/app_secret, Ollama URL, host KB path
```

### 2. Prepare the knowledge base

Drop Markdown files into `./coffee/` (or mount an existing directory at `/app/coffee`).
Chunks are split by `##` headings. Example:

```markdown
# Coffee Origins

## Ethiopia

Yirgacheffe is a famous coffee region in Ethiopia ...

## Kenya

Kenyan coffee is known for its vibrant fruity notes ...
```

### 3. Run with Docker (recommended)

```bash
docker compose up -d --build
docker logs faq-robot -f
```

Health check: `curl http://localhost:8081/health`

### 4. Run locally

```bash
pip install -r requirements.txt
python main.py --rebuild   # Build the FAISS index (first run)
python main.py --ws         # Start the WebSocket service
python main.py "What is Yirgacheffe coffee?"   # CLI single-shot Q&A
```

---

## Configuration (`.env`)

| Variable | Required | Description |
|---|---|---|
| `FEISHU_APP_ID` | ✅ | Feishu app ID |
| `FEISHU_APP_SECRET` | ✅ | Feishu app secret |
| `OLLAMA_BASE_URL` | ✅ | Ollama service URL, e.g. `http://localhost:11434` |
| `OLLAMA_MODEL` | ✅ | Model name, e.g. `qwen2.5:7b-instruct` |
| `EMBEDDING_MODEL` | | Embedding model, defaults to `moka-ai/m3e-base` |
| `SIMILARITY_THRESHOLD` | | Retrieval threshold, default `0.6` |
| `TOP_K` | | Retrieval top-K, default `3` |
| `COFFEE_HOST_PATH` | | Absolute host path of the KB, mounted to `/app/coffee` |
| `FEISHU_ADMIN_OPEN_ID` | | Admin open_id (receives feedback cards; auto-written by `绑定管理员` command) |
| `FEISHU_ADMIN_CHAT_ID` | | Admin group chat_id (alternative) |
| `FEISHU_WEBHOOK_URL` | | Webhook fallback URL (used when WebSocket admin is unset) |

---

## How to Use on Feishu

### End users

- **DM**: send your question directly
- **Group chat**: `@小光咖啡百科 your question`. The trigger name must match the value in [src/feishu_ws.py:105](src/feishu_ws.py#L105).

### Admin commands (DM the bot)

| Command | Effect |
|---|---|
| `绑定管理员` or `我是管理员` | Persists your open_id to `.env`. Future feedback cards land here. |
| `反馈列表` or `待处理反馈` | List the 10 most recent pending feedbacks. |
| `标记 <id> <status> [note]` | e.g. `标记 fb-20260603-001 已处理 added to KB` |
| `帮助` / `help` | Show command list. |

### Card buttons

Every new feedback is pushed as an interactive card with two buttons:
- **✓ 已处理** (primary, green) — marks as resolved, header turns green
- **✗ 已忽略** (danger, grey) — marks as ignored, header turns grey

After a click the buttons disappear and the card refreshes in place. Prerequisite: **card.action.trigger** event must be subscribed in the Feishu developer console.

---

## Anti-Hallucination

LLMs love to confidently invent facts. This project layers three defenses:

1. **Strict prompt** ([src/generator.py:8](src/generator.py#L8))
   - Forbid the model from using its own knowledge
   - No paraphrasing, no padding, no inference
   - Must return `暂无此信息` if the KB cannot answer
2. **Low temperature** (`0.3`) — reduce divergence
3. **Similarity floor** (`SIMILARITY_THRESHOLD=0.6`) — below this, retrieval returns nothing and generation is skipped (`no_context` feedback)

Verified ([test_e2e.py](test_e2e.py)):

| Question | Before | After |
|---|---|---|
| Flavor notes of Rwandan Kivu | Fabricated "citrus, strawberry" | 暂无此信息 ✓ |
| What is blockchain? | Gave a real definition | 暂无此信息 ✓ |
| Altitude of Costa Rica Tarrazú | Correct | 1500-1950m ✓ |

---

## Privacy & Security

- `.env`, `*.log`, `feedbacks/`, `memory/`, `debug_*.py` are all in `.gitignore`
- The host KB path (`COFFEE_HOST_PATH`) is passed via env var, never hard-coded
- Ollama runs locally / on LAN — knowledge-base contents never leave your network
- Before each commit, double-check: no `FEISHU_APP_SECRET`, no `FEISHU_WEBHOOK_URL`, no personal paths

---

## Tech Stack

- **Retrieval**: FAISS (inner product) + sentence-transformers (`moka-ai/m3e-base`)
- **Generation**: Ollama + Qwen2.5 family
- **Messaging**: lark-oapi WebSocket
- **Storage**: JSONL (feedback) / FAISS bin (index)
- **Runtime**: Python 3.11 + Docker

---

## License

MIT
