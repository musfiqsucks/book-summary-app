from flask import Flask, render_template, request
from dotenv import load_dotenv
import anthropic
import os

load_dotenv()

app = Flask(__name__)

MODEL = "claude-opus-5"

ACTIONS = {
    "summary": "Write a concise but insightful summary of the book '{book}' by {author}. Cover the main themes, plot, and key takeaways in a way that gives someone a solid understanding of the book.",
    "alternate_ending": "Imagine an alternate ending for the book '{book}' by {author}. Stay true to the characters and tone, but take the story in a different direction. Explain why this ending could also work.",
    "key_points": "List the 5 most important key points from the book '{book}' by {author}. For each point, provide a brief explanation of why it matters.",
    "main_plot": "Describe the main plot of the book '{book}' by {author}. Walk through the major events, turning points, and resolution in a clear narrative.",
    "suggestions": "Suggest 5 books similar to '{book}' by {author}. For each suggestion, explain briefly what it's about and why someone who enjoyed the original book would like it.",
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


@app.route("/health")
def health():
    return {"status": "ok", "api_key_configured": bool(os.getenv("ANTHROPIC_API_KEY"))}


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

        if not book_name or not author_name:
            error = "Please enter both a book name and author name."
        else:
            book_name = book_name.title()
            author_name = author_name.title()

            prompt = ACTIONS[selected_action].format(book=book_name, author=author_name)

            if not os.getenv("ANTHROPIC_API_KEY"):
                error = (
                    "Server configuration error: ANTHROPIC_API_KEY is not set. "
                    "Copy .env.example to .env and add your key."
                )
            else:
                try:
                    message = get_client().messages.create(
                        model=MODEL,
                        max_tokens=4096,
                        output_config={"effort": "low"},
                        messages=[{"role": "user", "content": prompt}],
                        system="You are a knowledgeable and thoughtful book expert. Provide well-written, engaging responses about books. Use clear paragraphs and formatting.",
                    )
                    if message.stop_reason == "refusal":
                        error = "That request could not be answered. Please try a different book."
                    else:
                        result = extract_text(message)
                        if not result:
                            error = "The model returned an empty response. Please try again."
                except anthropic.AuthenticationError:
                    error = "Invalid API key. Please check your configuration."
                except anthropic.RateLimitError:
                    error = "Rate limit reached. Please try again in a moment."
                except anthropic.APIConnectionError:
                    error = "Could not reach the Claude API. Check your network connection."
                except anthropic.APIStatusError as e:
                    error = f"The Claude API returned an error ({e.status_code}). Please try again."
                except Exception as e:
                    error = f"Something went wrong: {e}"

    return render_template(
        "index.html",
        result=result,
        error=error,
        book_name=book_name,
        author_name=author_name,
        selected_action=selected_action,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
