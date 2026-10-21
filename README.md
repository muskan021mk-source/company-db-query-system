# Company Database Query System

A secured web app where employees sign up and log in with company-verified credentials, then chat with an AI agent in plain English to query and explore the organization's data. No SQL required.

> Examples: *"Show all employees in Engineering"*, *"Who reports to Lisa Hernandez?"*, *"Update John's department"*

## Features

- **Natural-language queries** over the company database through an AI agent
- **Verified sign-up**: only people who exist in the PostgreSQL employee records can register, with email OTP verification
- **Org hierarchy questions** answered from a Neo4j graph (reporting lines, teams)
- **Chat history** saved per user
- **Charts** rendered in the chat for suitable results
- **LLM fallback chain**: if the primary model fails, the agent falls back to other Gemini and Groq models

## Architecture

```
React + Vite  ──►  FastAPI  ──►  PostgreSQL  (employee records, source of truth)
 (org-frontend)   (main_project)  ├─►  Neo4j     (org hierarchy)
                                  ├─►  MongoDB   (user accounts, chat history)
                                  └─►  LLMs via LiteLLM (Gemini, Groq)
```

| Layer | Technology |
|---|---|
| Frontend | React, Vite, Redux |
| Backend | FastAPI, Python 3.13 |
| Employee data | PostgreSQL |
| Org hierarchy | Neo4j |
| Users and chats | MongoDB |
| AI | LangChain / LangGraph, LiteLLM (Gemini, Groq) |
| Observability | Langfuse (optional) |

## Security

- Sessions use **JWT**; the app refuses to start without a strong `JWT_SECRET` (32+ characters)
- **Login lockout** after repeated failed attempts
- **Email OTP** verification and password reset flow
- **Permissions and row-level rules** control which tables and rows each user can read or change
- **Audit log** of actions, with a retention-based purge script (`purge_audit.py`) that runs under a separate low-privilege database user
- **Statement timeout** and a **large-write threshold** on database operations
- Secrets live in `.env` files, which are git-ignored

## Project structure

```
main_project/     FastAPI backend, agent, auth, permissions, DB scripts
  routes/         API routes (profile, user)
  agent.py        AI agent logic
  mcp_tools.py    Tools the agent can call
  sync_neo4j.py   Syncs the org hierarchy from PostgreSQL to Neo4j
  purge_audit.py  Deletes old audit records
org-frontend/     React + Vite frontend
```

## Getting started

### Prerequisites

- Python 3.13
- Node.js (current LTS)
- PostgreSQL, MongoDB and Neo4j running locally or hosted
- API keys for Gemini and/or Groq

### 1. Backend

```bash
cd main_project
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

Copy the environment template and fill in your values:

```bash
copy .env.example .env         # Windows
# cp .env.example .env         # macOS / Linux
```

Generate a JWT secret and paste it into `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set up the databases:

- Create the PostgreSQL database named in `POSTGRES_DB` and load your employee schema. The `*.sql` files in this folder add privacy roles and fixes on top of it.
- Sync the org hierarchy into Neo4j:

```bash
python sync_neo4j.py
```

Start the API:

```bash
uvicorn main:app --reload --port 4000
```

### 2. Frontend

```bash
cd org-frontend
copy .env.example .env         # Windows
# cp .env.example .env         # macOS / Linux
npm install
npm run dev
```

Open http://localhost:5173.

## Environment variables

See [`main_project/.env.example`](main_project/.env.example) and [`org-frontend/.env.example`](org-frontend/.env.example) for the full list. The main groups are:

| Group | Variables |
|---|---|
| LLM | `GEMINI_API_KEY`, `GROQ_API_KEY`, `PRIMARY_MODEL`, `FALLBACK_MODEL_1..4` |
| Auth | `JWT_SECRET`, `JWT_EXPIRES_MINUTES` |
| Email | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` |
| PostgreSQL | `POSTGRES_*`, `DATABASE_URL` |
| MongoDB | `MONGODB_URI`, `MONGODB_DB_NAME` |
| Neo4j | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` |
| Frontend | `VITE_API_URL`, `VITE_BASE_URL` |

**Never commit your real `.env` files.**

## Tests

Scripts in `main_project/` (`test_login_lockout.py`, `test_permissions1.py`, `test_row_rules.py`, `test_revert_rules.py`) cover login lockout, permissions and row-level rules. Run them against a development database only:

```bash
python test_login_lockout.py
```

## Author

Built by [@muskan021mk-source](https://github.com/muskan021mk-source).
