# Bookish

A small Flask app that answers questions about books with the Claude API — summaries,
key points, plot, alternate endings, similar titles — and lets a reader download the
result as a PDF in exchange for their email address.

---

## ⚠️ Read this before collecting real email addresses

**By default, captured emails are written to `leads.jsonl` on the container disk, and
Railway wipes that disk on every deploy.**

Until you configure one of the options below, anyone who enters their email is handing
it to a file that gets deleted. If the app is live and collecting now, fix this *before*
the next deploy rather than after — a deploy is what destroys the data, so the addresses
collected so far are still there until you push again.

You can verify the current state at any time: `GET /healthz` reports whether the API key
is configured, and the app logs a warning at startup when `DATABASE_URL` is unset.

### Option A — Email each address to yourself (no database, fastest)

Set these in Railway → your service → **Variables**:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=your-16-char-app-password
SMTP_FROM=you@gmail.com
LEAD_NOTIFY_EMAIL=you@gmail.com
```

For Gmail, `SMTP_PASS` must be an **App Password** — Google Account → Security →
2-Step Verification → App passwords. Your normal account password will fail to
authenticate.

Sending runs on a background thread, so it never delays the reader's download, and a
failed send is logged rather than blocking the PDF. `Reply-To` is set to the reader's
address so you can answer them directly.

This notifies you but keeps no list of its own — pair it with Option B or C if you want
a durable record.

### Option B — Postgres (durable, recommended)

Railway → your project → **New → Database → Add PostgreSQL**. Railway injects
`DATABASE_URL` into the service automatically; the app picks it up on next boot and
creates the `pdf_leads` table on the first download.

```sql
SELECT email, book_title, author, action, created_at
FROM pdf_leads ORDER BY created_at DESC;
```

### Option C — A Railway Volume (a real file that survives deploys)

Attach a **Volume** mounted at `/data`. The app detects it automatically and writes
`/data/leads.jsonl` there — no extra configuration. Unlike the default container disk,
a Volume persists across deploys.

### Reading the list back

Set `LEADS_TOKEN` to a long random string, then:

```
GET /admin/leads?token=<LEADS_TOKEN>
```

It returns every captured lead as JSON, reading from Postgres or the JSONL file,
whichever is active. **While `LEADS_TOKEN` is unset the endpoint returns 404**, so it
does not exist by default.

### A note on the data

These are real email addresses, which makes them personal data. The download form has a
consent checkbox, and `leads.jsonl` is gitignored so it can never be committed. If you
have EU users, GDPR also expects a privacy note saying what you will use the address for
and a way to unsubscribe — that copy is yours to write.

---

## Running locally

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env          # then add your ANTHROPIC_API_KEY
./venv/bin/python app.py
```

Then open http://localhost:5000.

On macOS, port 5000 is taken by the AirPlay Receiver and will answer with a 403. Either
turn it off in System Settings → General → AirDrop & Handoff, or run on another port:

```bash
PORT=5050 ./venv/bin/python app.py
```

## Configuration

Every setting is an environment variable; see `.env.example` for the annotated list.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** From https://console.anthropic.com/ |
| `PORT` | `5000` | Injected by Railway in production |
| `DATABASE_URL` | — | Postgres for captured emails (Option B) |
| `LEADS_FILE` | `/data/leads.jsonl` if a volume is mounted, else `leads.jsonl` | JSONL fallback |
| `LEADS_TOKEN` | — | Enables `GET /admin/leads`; 404 while unset |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` | — | Email notification (Option A) |
| `LEAD_NOTIFY_EMAIL` | — | Where lead notifications are sent |
| `MAX_UPLOAD_MB` | `5` | Upload size cap |
| `MAX_BOOK_CHARS` | `300000` | Cap on extracted text sent to the API |
| `FLASK_DEBUG` | off | Never enable in production |

### Cost

`MAX_BOOK_CHARS` is the setting that controls spend, not `MAX_UPLOAD_MB`. At the default
300,000 characters an uploaded book is roughly 75k input tokens per request. The book
text is sent as a cached block, so running several actions against the same upload
within a few minutes reuses the prefix and costs much less — but the first request pays
full price. Lower `MAX_BOOK_CHARS` if that matters more than covering long books.

## Languages

The form has a language picker: **English** (default), **বাংলা**, or **Both** (the full
answer in English, a `===` rule, then the complete Bangla translation).

Bangla PDFs need real text shaping — Bengali forms conjuncts and moves some vowel signs
in front of their consonant. PDFs are therefore generated with **fpdf2 + uharfbuzz**,
with Noto Serif for Latin and Noto Serif Bengali as a per-glyph fallback (both bundled
under `static/fonts/`, SIL Open Font License). ReportLab cannot do this: it writes one
glyph per codepoint with no shaping, which leaves Bengali malformed in any viewer that
does not silently compensate.

If `uharfbuzz` is unavailable the app still produces PDFs — it logs a warning and Latin
output is unaffected, but Bangla loses shaping.

## Routes

| Route | Purpose |
|---|---|
| `GET /` | The app |
| `POST /` | Run an action; returns JSON for `X-Requested-With: fetch`, else HTML |
| `POST /api/suggest-book` | Identify a book from a description; returns up to 5 matches |
| `POST /api/download-pdf` | Generate the PDF; refuses without a valid email and consent |
| `GET /admin/leads` | Export captured emails; needs `LEADS_TOKEN` |
| `GET /healthz` | Health check used by `railway.toml` |

## Deployment

Railway builds from the `Dockerfile` (see `railway.toml`) and health-checks `/healthz`.
Gunicorn binds `$PORT`, which Railway injects.
