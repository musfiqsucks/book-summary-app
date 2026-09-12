from flask import Flask, render_template, request, jsonify, send_file
from dotenv import load_dotenv
import anthropic
import datetime
import io
import json
import os
import re

load_dotenv()

app = Flask(__name__)

MODEL = "claude-opus-5"

# Upload limits. MAX_UPLOAD_MB caps the request body; MAX_BOOK_CHARS caps how much
# extracted text we actually send to the API, which is what drives cost.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "5"))
MAX_BOOK_CHARS = int(os.getenv("MAX_BOOK_CHARS", "300000"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# Where the JSONL fallback lives. Prefer a mounted volume if one is present:
# on Railway, attaching a Volume at /data makes this survive deploys.
def _default_leads_file():
    for d in ("/data", "/var/data"):
        if os.path.isdir(d) and os.access(d, os.W_OK):
            return os.path.join(d, "leads.jsonl")
    return "leads.jsonl"


LEADS_FILE = os.getenv("LEADS_FILE") or _default_leads_file()
LEADS_TOKEN = os.getenv("LEADS_TOKEN", "")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")

TEACHING_FORMAT = (
    "Write 8-12 teachings. Use exactly this structure for each one:\n\n"
    "## <a short maxim of 3-8 words, in the voice of a teacher>\n\n"
    "<One paragraph of 3-5 sentences revealing what the book shows and why it matters "
    "to a life. Ground it in specifics - a character, a moment, a turn of the story. "
    "Quiet authority, plain language, no hype.>\n\n"
    "> <One practice the student can do today. A single imperative sentence.>\n\n"
    "Separate each teaching with a line containing only ---\n\n"
    "Close with a final section:\n\n"
    "## The Seven Days\n\n"
    "Seven lines, each 'Day N - <a small concrete action>'.\n\n"
    "Rules:\n"
    "- Never label the parts. The words 'Learning', 'Why it enriches life', "
    "'How to apply today' and 'Example' must not appear.\n"
    "- No bullet lists and no bold labels. Headings and prose only.\n"
    "- Address the reader as 'you'. Avoid motivational cliche and avoid flattery.\n"
    "- Do not invent events that are not in the book."
)

PROSE_FORMAT = (
    "Write in flowing prose under short '## ' headings where a break is genuinely needed. "
    "Do not use bullet lists or bold labels. Speak plainly, with the calm authority of "
    "someone who knows the book well."
)

ACTIONS = {
    "summary": (
        "Give the essence of '{book}' by {author} - its themes, its movement, and what a "
        "reader carries away from it.\n\n" + PROSE_FORMAT
    ),
    "alternate_ending": (
        "Imagine an alternate ending for '{book}' by {author}. Stay true to its characters "
        "and tone, then show why this ending could also be true.\n\n" + PROSE_FORMAT
    ),
    "enrich_life_key_points": (
        "You are passing on the distilled wisdom of '{book}' by {author} to a student who "
        "wants to live better.\n\n" + TEACHING_FORMAT
    ),
    "main_plot": (
        "Tell the story of '{book}' by {author} - its major events, turning points, and "
        "resolution.\n\n" + PROSE_FORMAT
    ),
    "suggestions": (
        "Name 5 books that belong beside '{book}' by {author}. For each, say what it is and "
        "why it will speak to someone who valued this one. Use a '## ' heading per book, "
        "then a short paragraph. No bullet lists, no bold labels."
    ),
}

# When the user uploads the book, work from the supplied text rather than recall.
UPLOAD_ACTIONS = {
    "summary": "Give the essence of the book above - its themes, its movement, and what a reader carries away.\n\n" + PROSE_FORMAT,
    "alternate_ending": "Imagine an alternate ending for the book above. Stay true to its characters and tone, then show why it could also be true.\n\n" + PROSE_FORMAT,
    "enrich_life_key_points": "You are passing on the distilled wisdom of the book above to a student who wants to live better.\n\n" + TEACHING_FORMAT,
    "main_plot": "Tell the story of the book above - its major events, turning points, and resolution.\n\n" + PROSE_FORMAT,
    "suggestions": "Name 5 books that belong beside the book above. Use a '## ' heading per book, then a short paragraph. No bullet lists, no bold labels.",
}

ACTION_LABELS = {
    "summary": "Summary",
    "alternate_ending": "Alternate Ending",
    "enrich_life_key_points": "Key Points to Enrich Your Life",
    "main_plot": "Main Plot",
    "suggestions": "Similar Books",
}

_client = None


def get_client():
    """Build the Anthropic client once, on first use."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def extract_text(message):
    """Pull the text out of a response, skipping thinking and other block types."""
    return "\n".join(b.text for b in message.content if b.type == "text").strip()


def wants_json():
    return request.headers.get("X-Requested-With") == "fetch"


def read_pdf(file_storage):
    """Extract text from an uploaded PDF. Returns (text, error)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "PDF support is not installed on the server (missing pypdf)."

    try:
        reader = PdfReader(io.BytesIO(file_storage.read()))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return None, "That PDF is password protected. Please upload an unlocked copy."

        pages = []
        total = 0
        for page in reader.pages:
            chunk = page.extract_text() or ""
            pages.append(chunk)
            total += len(chunk)
            if total >= MAX_BOOK_CHARS:
                break

        text = "\n".join(pages).strip()
    except Exception:
        return None, "That file could not be read as a PDF. Please upload a valid PDF."

    if not text:
        return None, (
            "No text could be extracted from that PDF. It is likely a scanned image, "
            "which needs OCR before it can be read."
        )

    return text[:MAX_BOOK_CHARS], None


def run_action(selected_action, book_name, author_name, book_text=None):
    """Call the API for one action. Returns (result, error)."""
    if selected_action == "enrich_life_key_points":
        system_msg = (
            "You are an old teacher passing knowledge to a student who came to you with a "
            "question. You have read the book many times. Speak with restraint and warmth - "
            "the authority is in the clarity, never in decoration. Be concrete and never "
            "invent events from the book. Follow the requested structure exactly."
        )
        max_tokens = 8192
    else:
        system_msg = (
            "You are an old teacher passing knowledge to a student. You have read the book "
            "many times. Speak plainly and with restraint; the authority is in the clarity. "
            "Never invent events from the book. Follow the requested structure exactly."
        )
        max_tokens = 4096

    if book_text:
        system_msg += (
            " The full text of the book is provided by the user. Base your answer on that text, "
            "not on prior knowledge. If the text appears truncated, say so briefly."
        )
        content = [
            # Stable part first so repeat actions on the same upload hit the cache.
            {
                "type": "text",
                "text": f"Here is the book text:\n\n{book_text}",
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": UPLOAD_ACTIONS[selected_action]},
        ]
    else:
        content = ACTIONS[selected_action].format(book=book_name, author=author_name)

    try:
        message = get_client().messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": content}],
            system=system_msg,
        )
        if message.stop_reason == "refusal":
            return "", "That request could not be answered. Please try a different book."

        result = extract_text(message)
        if not result:
            return "", "The model returned an empty response. Please try again."
        return result, ""
    except anthropic.AuthenticationError:
        return "", "Invalid API key. Please check your configuration."
    except anthropic.RateLimitError:
        return "", "Rate limit reached. Please try again in a moment."
    except anthropic.APIConnectionError:
        return "", "Could not reach the Claude API. Check your network connection."
    except anthropic.APIStatusError as e:
        return "", f"The Claude API returned an error ({e.status_code}). Please try again."
    except Exception as e:
        return "", f"Something went wrong: {e}"


# --- Email capture -----------------------------------------------------------


def store_lead(email, book_title, author, action, consent):
    """Record an email before handing over a PDF.

    Uses Postgres when DATABASE_URL is set (add a Postgres service on Railway and
    it is injected automatically). Falls back to a local JSONL file otherwise -
    note that on Railway a container filesystem is wiped on every deploy, so the
    fallback is for local development only.
    """
    row = {
        "email": email,
        "book_title": book_title,
        "author": author,
        "action": action,
        "consent": consent,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    dsn = os.getenv("DATABASE_URL")
    if dsn:
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS pdf_leads (
                            id SERIAL PRIMARY KEY,
                            email TEXT NOT NULL,
                            book_title TEXT,
                            author TEXT,
                            action TEXT,
                            consent BOOLEAN,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        "INSERT INTO pdf_leads (email, book_title, author, action, consent)"
                        " VALUES (%s, %s, %s, %s, %s)",
                        (email, book_title, author, action, consent),
                    )
            return True
        except Exception as e:
            app.logger.error("Could not write lead to Postgres: %s", e)
            return False

    try:
        with open(LEADS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        app.logger.warning(
            "DATABASE_URL is not set - lead written to %s, which is ephemeral on Railway.",
            LEADS_FILE,
        )
        return True
    except Exception as e:
        app.logger.error("Could not write lead to %s: %s", LEADS_FILE, e)
        return False


def build_pdf(title, author, action_label, body):
    """Render the result as a PDF and return it as a BytesIO."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"{title} - {action_label}",
        author="Bookish",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "BookishTitle", parent=styles["Title"], fontSize=20, leading=24, alignment=0,
        textColor=colors.HexColor("#2D2B28"), spaceAfter=2,
    )
    meta = ParagraphStyle(
        "BookishMeta", parent=styles["Normal"], fontSize=11, leading=14,
        textColor=colors.HexColor("#6B6560"), spaceAfter=10,
    )
    body_style = ParagraphStyle(
        "BookishBody", parent=styles["BodyText"], fontSize=10.5, leading=16,
        textColor=colors.HexColor("#2D2B28"), spaceAfter=8,
    )

    teach = ParagraphStyle(
        "BookishTeaching", parent=styles["Normal"], fontName="Times-Bold", fontSize=13,
        leading=17, textColor=colors.HexColor("#2D2B28"), spaceBefore=14, spaceAfter=6,
    )
    practice = ParagraphStyle(
        "BookishPractice", parent=styles["Normal"], fontName="Times-Italic", fontSize=10.5,
        leading=15, textColor=colors.HexColor("#6B6560"), leftIndent=12,
        borderPadding=0, spaceBefore=4, spaceAfter=10,
    )

    story = [
        Paragraph(escape_pdf(title), h1),
        Paragraph(escape_pdf(f"by {author}  -  {action_label}"), meta),
        HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#E8E4DF")),
        Spacer(1, 8),
    ]

    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            story.append(Spacer(1, 5))
            continue

        if line in ("---", "***", "___"):
            story.append(Spacer(1, 4))
            story.append(HRFlowable(width="34%", thickness=0.6,
                                    color=colors.HexColor("#E8E4DF"), hAlign="CENTER"))
            story.append(Spacer(1, 4))
            continue

        if line.startswith("#"):
            story.append(Paragraph(markdown_inline(escape_pdf(line.lstrip("#").strip())), teach))
            continue

        if line.startswith(">"):
            story.append(Paragraph(markdown_inline(escape_pdf(line.lstrip(">").strip())), practice))
            continue

        story.append(Paragraph(markdown_inline(escape_pdf(line)), body_style))

    doc.build(story)
    buf.seek(0)
    return buf


def escape_pdf(text):
    """Escape XML special chars so reportlab's mini-markup does not choke."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_inline(text):
    """Turn **bold** and *italic* into reportlab's inline markup."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    return text


# --- Routes ------------------------------------------------------------------


@app.route("/healthz")
def healthz():
    """Railway health check (railway.toml -> healthcheckPath)."""
    return jsonify(status="ok", api_key_configured=bool(os.getenv("ANTHROPIC_API_KEY"))), 200


@app.errorhandler(413)
def too_large(e):
    msg = f"That file is too large. The maximum upload size is {MAX_UPLOAD_MB} MB."
    if wants_json():
        return jsonify({"error": msg}), 413
    return render_template("index.html", result="", error=msg, book_name="",
                           author_name="", selected_action="summary",
                           max_upload_mb=MAX_UPLOAD_MB), 413


@app.route("/", methods=["GET", "POST"])
def home():
    result = ""
    book_name = ""
    author_name = ""
    selected_action = "summary"
    error = ""

    if request.method == "POST":
        book_name = request.form.get("book_name", "").strip()
        author_name = request.form.get("author_name", "").strip()
        selected_action = request.form.get("action", "summary")

        if selected_action not in ACTIONS:
            selected_action = "summary"

        upload = request.files.get("book_file")
        has_upload = bool(upload and upload.filename)

        book_text = None
        if has_upload:
            if not upload.filename.lower().endswith(".pdf"):
                error = "Only PDF files are supported."
            else:
                book_text, error = read_pdf(upload)
                if book_text:
                    # With the text in hand, title and author are nice-to-have.
                    if not book_name:
                        book_name = os.path.splitext(os.path.basename(upload.filename))[0]
                    if not author_name:
                        author_name = "Unknown author"
        elif not book_name or not author_name:
            error = "Please enter both a book name and author name."

        if not error:
            book_name = book_name.title() if not has_upload else book_name
            author_name = author_name.title() if not has_upload else author_name

            if not os.getenv("ANTHROPIC_API_KEY"):
                error = (
                    "Server configuration error: ANTHROPIC_API_KEY is not set. "
                    "Copy .env.example to .env and add your key."
                )
            else:
                result, error = run_action(selected_action, book_name, author_name, book_text)

        if wants_json():
            if error:
                return jsonify({"error": error}), 200
            return jsonify({
                "result": result,
                "book_name": book_name,
                "author_name": author_name,
                "action": selected_action,
                "action_label": ACTION_LABELS.get(selected_action, "Result"),
            })

    return render_template(
        "index.html",
        result=result,
        error=error,
        book_name=book_name,
        author_name=author_name,
        selected_action=selected_action,
        max_upload_mb=MAX_UPLOAD_MB,
    )


@app.route("/api/suggest-book", methods=["POST"])
def suggest_book():
    data = request.get_json(silent=True) or {}
    description = (data.get("description") or "").strip()
    if not description:
        return jsonify({"error": "Please provide a description of the book."}), 400

    if not os.getenv("ANTHROPIC_API_KEY"):
        return jsonify({"error": "Server configuration error: API key not set."}), 500

    try:
        message = get_client().messages.create(
            model=MODEL,
            max_tokens=2048,
            output_config={"effort": "low"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"A user is trying to remember a book. Here is their description:\n\n"
                        f'"{description}"\n\n'
                        f"Identify up to 5 books that could match, best match first. "
                        f"Only include genuinely plausible candidates - fewer is better than padding "
                        f"the list. Respond with ONLY valid JSON in this exact format:\n"
                        f'{{"matches": [{{"title": "Book Title", "author": "Author Name", '
                        f'"year": "1953", "confidence": "high/medium/low", '
                        f'"reasoning": "One sentence explaining why this matches"}}]}}'
                    ),
                }
            ],
            system="You are a book identification expert. Always respond with valid JSON only, no other text.",
        )
        if message.stop_reason == "refusal":
            return jsonify({"error": "Could not identify the book. Try adding more details."}), 422

        response_text = extract_text(message)
        # The model may wrap JSON in a ```json fence despite the instruction.
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        parsed = json.loads(response_text)
        matches = parsed.get("matches") or []
        if not matches:
            return jsonify({"error": "No close matches found. Try adding more details."}), 422

        return jsonify({"matches": matches[:5]})
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key."}), 401
    except anthropic.RateLimitError:
        return jsonify({"error": "Rate limit reached. Try again shortly."}), 429
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return jsonify({"error": "Could not identify the book. Try adding more details."}), 422
    except anthropic.APIConnectionError:
        return jsonify({"error": "Could not reach the Claude API."}), 503
    except Exception as e:
        return jsonify({"error": f"Something went wrong: {e}"}), 500


@app.route("/admin/leads")
def export_leads():
    """Export captured emails as JSON.

    Protected by LEADS_TOKEN: call /admin/leads?token=<LEADS_TOKEN>. Returns 404
    when no token is configured, so the endpoint does not exist by default.
    """
    if not LEADS_TOKEN:
        return jsonify({"error": "Not found"}), 404
    if request.args.get("token") != LEADS_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    dsn = os.getenv("DATABASE_URL")
    if dsn:
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT email, book_title, author, action, consent, created_at"
                        " FROM pdf_leads ORDER BY created_at DESC"
                    )
                    cols = [c.name for c in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            for r in rows:
                r["created_at"] = r["created_at"].isoformat()
            return jsonify({"source": "postgres", "count": len(rows), "leads": rows})
        except Exception as e:
            app.logger.error("Could not read leads from Postgres: %s", e)
            return jsonify({"error": "Could not read leads."}), 500

    try:
        with open(LEADS_FILE, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        return jsonify({"source": LEADS_FILE, "count": len(rows), "leads": rows})
    except FileNotFoundError:
        return jsonify({"source": LEADS_FILE, "count": 0, "leads": []})
    except Exception as e:
        app.logger.error("Could not read %s: %s", LEADS_FILE, e)
        return jsonify({"error": "Could not read leads."}), 500


@app.route("/api/download-pdf", methods=["POST"])
def download_pdf():
    """Generate the PDF server-side, but only in exchange for an email address."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    consent = bool(data.get("consent"))
    title = (data.get("title") or "Untitled").strip()
    author = (data.get("author") or "Unknown author").strip()
    action = data.get("action") or "summary"
    body = (data.get("body") or "").strip()

    if not EMAIL_RE.match(email) or len(email) > 254:
        return jsonify({"error": "Please enter a valid email address."}), 400
    if not consent:
        return jsonify({"error": "Please agree to receive the PDF at this address."}), 400
    if not body:
        return jsonify({"error": "There is no result to download yet."}), 400

    stored = store_lead(email, title, author, action, consent)
    if not stored:
        return jsonify({"error": "Could not record your email. Please try again."}), 500

    try:
        pdf = build_pdf(title, author, ACTION_LABELS.get(action, "Result"), body)
    except Exception as e:
        app.logger.error("PDF generation failed: %s", e)
        return jsonify({"error": "Could not generate the PDF. Please try again."}), 500

    filename = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_") or "bookish"
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{filename}_Bookish.pdf",
    )


if not os.getenv("DATABASE_URL"):
    app.logger.warning(
        "DATABASE_URL is not set. Captured emails go to %s. If that path is not a "
        "mounted volume, it is WIPED on every deploy - attach a Postgres service "
        "or a volume before collecting real addresses.",
        LEADS_FILE,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
