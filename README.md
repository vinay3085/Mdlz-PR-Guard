# Mdlz PR Guard

**AI-Powered PR Security & Org Policy Scanner** — A GitHub App that automatically reviews pull requests for security vulnerabilities, secrets in code, and org-policy violations using static analysis (Semgrep + Gitleaks) and an LLM (Anthropic Claude).

---

## What It Does

When a PR is opened or updated:
1. **Fetches the PR diff** via the GitHub API
2. **Runs Semgrep** to detect common vulnerability patterns
3. **Runs Gitleaks** to detect secrets or credentials in the diff
4. **Checks org policies** (ticket reference, description length, PR size, etc.)
5. **Calls Claude** for contextual security analysis beyond what static tools catch
6. **Posts a PR Review comment** summarising all findings
7. **Creates a GitHub Check Run** that can gate merges on security pass/fail

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| pip | latest | included with Python |
| Semgrep | latest | `pip install semgrep` |
| Gitleaks | v8+ | [github.com/gitleaks/gitleaks](https://github.com/gitleaks/gitleaks/releases) |
| ngrok | latest | [ngrok.com/download](https://ngrok.com/download) |

---

## Installation

```bash
# 1. Clone / navigate to the project directory
cd d:\Project_Current\Git-PR-Scan

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the example env file
copy .env.example .env   # Windows
cp .env.example .env      # macOS/Linux
```

---

## GitHub App Setup

### Step 1 — Register a new GitHub App

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
2. Set:
   - **GitHub App name:** `Mdlz PR Guard` (or any name)
   - **Homepage URL:** `http://localhost:8000`
   - **Webhook URL:** `https://<your-ngrok-subdomain>.ngrok-free.app/webhook` *(update after starting ngrok)*
   - **Webhook secret:** Generate a strong random string (e.g. `openssl rand -hex 32`) — copy it
3. **Permissions** (Repository):
   - `Pull requests`: Read & Write
   - `Checks`: Read & Write
   - `Contents`: Read
4. **Subscribe to events:**
   - `Pull request`
   - `Installation`
5. Click **Create GitHub App**

### Step 2 — Generate a Private Key

1. In your new GitHub App page, scroll to **Private keys** → **Generate a private key**
2. Download the `.pem` file
3. Create a `certs/` directory and place the key there:
   ```
   mkdir certs
   copy <downloaded-key>.pem certs\private_key.pem
   ```

### Step 3 — Fill in the .env file

Open `.env` and set:

```env
GITHUB_APP_ID=<your app's numeric ID from the App settings page>
GITHUB_PRIVATE_KEY_PATH=./certs/private_key.pem
GITHUB_WEBHOOK_SECRET=<the random string you chose above>

ANTHROPIC_API_KEY=<your Anthropic API key from console.anthropic.com>
LLM_MODEL=claude-opus-5   # or claude-sonnet-5 for lower cost
```

### Step 4 — Install the App on a repository

1. In the GitHub App settings → **Install App** → select the org/repo you want to test with

---

## Running Locally

### Start the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Start ngrok (in a new terminal)

```bash
ngrok http 8000
```

Copy the `https://*.ngrok-free.app` URL and set it as the **Webhook URL** in your GitHub App settings (append `/webhook`):

```
https://abc123.ngrok-free.app/webhook
```

### Verify the app is running

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"mdlz-pr-guard"}
```

### Test with a PR

Open or update a pull request in the repo where you installed the app. Within seconds you should see:
- A **PR Review comment** from your GitHub App bot
- A **Check Run** result (pass/warn/fail) in the Checks tab

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_APP_ID` | ✅ | — | Numeric GitHub App ID |
| `GITHUB_PRIVATE_KEY_PATH` | | `./certs/private_key.pem` | Path to RSA private key PEM (local) |
| `GITHUB_PRIVATE_KEY_CONTENT` | | — | Full PEM content as a string (cloud deployments — takes precedence over path) |
| `GITHUB_WEBHOOK_SECRET` | ✅ | — | Webhook HMAC secret (min 8 chars) |
| `LLM_PROVIDER` | | `openai` | `openai` \| `anthropic` \| `databricks` |
| `LLM_MODEL` | | `gpt-4o` | Model name — must match provider |
| `OPENAI_API_KEY` | ✅ (openai) | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | ✅ (anthropic) | — | Anthropic API key |
| `DATABRICKS_HOST` | ✅ (databricks) | — | Workspace host without `https://` |
| `DATABRICKS_TOKEN` | ✅ (databricks) | — | Databricks Personal Access Token |
| `FEATURE_STATIC_ANALYSIS` | | `false` | Enable Semgrep scanning |
| `FEATURE_SECRET_SCANNING` | | `false` | Enable Gitleaks secret scanning |
| `FEATURE_POLICY_CHECK` | | `false` | Enable org policy checks |
| `FEATURE_LLM_FINDINGS` | | `false` | Enable LLM security findings |
| `LANGSMITH_TRACING` | | `false` | Enable LangSmith tracing |
| `LANGSMITH_API_KEY` | | — | LangSmith API key |
| `LANGSMITH_PROJECT` | | `mdlz-pr-guard` | LangSmith project name |
| `DATABASE_URL` | | `sqlite:///./mdlz_pr_guard.db` | SQLAlchemy connection string |
| `PROMPTS_DIR` | | `./prompts` | Directory containing prompt files |
| `APP_HOST` | | `0.0.0.0` | Bind host |
| `APP_PORT` | | `8000` | Bind port |
| `LOG_LEVEL` | | `INFO` | Logging level |

---

## Customising Policy Rules

Edit `app/services/policy_checker.py`. Each rule is a separate method:

| Rule ID | Checks | Severity |
|---|---|---|
| POLICY-001 | Ticket reference in title or body | medium |
| POLICY-002 | PR description ≥ 50 characters | low |
| POLICY-003 | PR title ≥ 10 characters | low |
| POLICY-004 | Total line changes ≤ 1000 | medium |
| POLICY-005 | Draft PR warning | info |

---

## Customising the LLM Prompt

Edit the files in `prompts/`:
- `system_prompt.txt` — The LLM's role and output schema instructions
- `user_prompt_template.txt` — The per-PR prompt with `{diff}`, `{static_findings}`, `{policy_violations}` placeholders

---

## Deploying to Databricks

Databricks Apps gives PR Guard a permanent public HTTPS URL — no ngrok required. The app runs as a long-lived web server inside your Databricks workspace, accessible from GitHub's webhook delivery network.

### Prerequisites

| Requirement | Notes |
|---|---|
| Databricks workspace | Standard or Premium tier |
| Databricks Apps enabled | Available on AWS, Azure, and GCP |
| Databricks CLI ≥ 0.210 | `pip install databricks-cli` or brew/winget |

### Step 1 — Install the Databricks CLI and authenticate

```bash
pip install databricks-cli
databricks configure --token
# Enter your workspace URL: https://adb-<id>.azuredatabricks.net
# Enter your Personal Access Token (User Settings → Developer → Access tokens)
```

### Step 2 — Create the Databricks App

```bash
# From the project root
databricks apps create mdlz-pr-guard --source-code-path .
```

This creates the app and starts a first deployment. Once deployed, the app is available at:

```
https://mdlz-pr-guard-<workspace-id>.databricksapps.com
```

This is your permanent webhook URL — use `https://mdlz-pr-guard-<workspace-id>.databricksapps.com/webhook`.

### Step 3 — Store secrets in Databricks

The GitHub private key must **never** live in a file on Databricks. Store it as an inline env var instead.

**Get the key as a single-line string:**

```bash
# On macOS/Linux — output the PEM as a single line with \n between lines
awk 'NF {printf "%s\\n", $0}' certs/private_key.pem

# On Windows PowerShell
(Get-Content certs\private_key.pem) -join "\n"
```

**Set environment variables in the Databricks Apps UI:**

1. Go to **Databricks UI → Compute → Apps → mdlz-pr-guard → Environment**
2. Add the following key/value pairs (all are secret — tick "Secret"):

| Variable | Value |
|---|---|
| `GITHUB_APP_ID` | your numeric App ID |
| `GITHUB_WEBHOOK_SECRET` | your webhook HMAC secret |
| `GITHUB_PRIVATE_KEY_CONTENT` | full PEM content (single line with `\n`) |
| `LLM_PROVIDER` | `databricks` |
| `DATABRICKS_HOST` | `adb-<id>.azuredatabricks.net` (no `https://`) |
| `DATABRICKS_TOKEN` | your Personal Access Token |
| `LLM_MODEL` | `databricks-meta-llama-3-3-70b-instruct` |

> **Note:** Leave `GITHUB_PRIVATE_KEY_PATH` unset — `GITHUB_PRIVATE_KEY_CONTENT` takes precedence.

### Step 4 — Deploy updates

```bash
databricks apps deploy mdlz-pr-guard --source-code-path .
```

Or using Asset Bundles (declarative, CI/CD-friendly):

```bash
databricks bundle deploy          # dev target
databricks bundle deploy -t prod  # prod target
```

### Step 5 — Update the GitHub App webhook URL

Because the app now has a stable URL, you need to update the GitHub App settings:

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → your app → Edit**
2. Update **Webhook URL** from the ngrok URL to:
   ```
   https://mdlz-pr-guard-<workspace-id>.databricksapps.com/webhook
   ```
3. Leave **Webhook secret** unchanged
4. Click **Save changes**
5. Open a test PR — you should see the review comment appear within a few seconds

### Databricks LLM — Free Llama 3.3

When `LLM_PROVIDER=databricks`, PR Guard uses the **Databricks Foundation Model API** — an OpenAI-compatible endpoint served by your workspace. The default model is:

```
databricks-meta-llama-3-3-70b-instruct
```

This is Meta's Llama 3.3 70B Instruct, available for free (pay-per-token, included in most Databricks subscriptions). To use a different Foundation Model API model, set `LLM_MODEL` to any of:

| Model ID | Notes |
|---|---|
| `databricks-meta-llama-3-3-70b-instruct` | **Default** — Llama 3.3 70B, strong reasoning |
| `databricks-meta-llama-3-1-70b-instruct` | Llama 3.1 70B |
| `databricks-dbrx-instruct` | Databricks DBRX |
| `databricks-mixtral-8x7b-instruct` | Mixtral 8x7B, lower cost |

> The Foundation Model API endpoint is `https://<DATABRICKS_HOST>/serving-endpoints`. PR Guard constructs this automatically from the `DATABRICKS_HOST` env var.

### Database note

SQLite state in Databricks Apps is **ephemeral** — it resets on each deployment. For persistent storage, change `DATABASE_URL` to a PostgreSQL connection string (e.g. hosted on Azure Database for PostgreSQL or AWS RDS) and install `psycopg2-binary`.

---

## Production Considerations

- **Database:** Change `DATABASE_URL` to a PostgreSQL connection string; install `psycopg2-binary`
- **Queue:** Replace FastAPI `BackgroundTasks` with Celery + Redis or AWS SQS for reliable retries
- **Secrets:** Use a secrets manager (AWS Secrets Manager, HashiCorp Vault) instead of `.env` files
- **Deployment:** Containerise with Docker; deploy to ECS, Cloud Run, or Kubernetes
- **Monitoring:** Add structured logging and ship to your SIEM / observability platform

---

## Architecture Decision Records

- [ADR-001 — Tech Stack Selection](docs/adr/ADR-001-tech-stack-selection.md)
- [ADR-002 — LLM Provider](docs/adr/ADR-002-llm-provider.md)
- [ADR-003 — SQLite for PoC](docs/adr/ADR-003-storage-sqlite-poc.md)
- [ADR-004 — Async Webhook Processing](docs/adr/ADR-004-webhook-async-processing.md)

---

## Security Notes

- The private key (`certs/private_key.pem`) and `.env` file are gitignored — never commit them
- Webhook signature is verified using `hmac.compare_digest` (timing-safe) before any payload processing
- All database access uses SQLAlchemy ORM — no raw SQL
- Subprocess calls to Semgrep/Gitleaks use explicit argument lists (no `shell=True`)
