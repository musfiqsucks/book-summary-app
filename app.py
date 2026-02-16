from flask import Flask, render_template, request, jsonify
import anthropic
import os

app = Flask(__name__)

ACTIONS = {
    "summary": "Write a concise but insightful summary of the book '{book}' by {author}. Cover the main themes, plot, and key takeaways in a way that gives someone a solid understanding of the book.",
    "alternate_ending": "Imagine an alternate ending for the book '{book}' by {author}. Stay true to the characters and tone, but take the story in a different direction. Explain why this ending could also work.",
    "enrich_life_key_points": (
        "From the book '{book}' by {author}, extract the most meaningful learnings and present them as "
        "point-by-point, descriptive takeaways designed to enrich a person's life.\n\n"
        "Produce 8-12 numbered points. For each point include:\n"
        "1. **Learning** — the core idea from the book\n"
        "2. **Why it enriches life** — how it improves emotions, mental clarity, relationships, work, or health (1-2 lines)\n"
        "3. **How to apply today** — one small, concrete action you can take right now\n"
        "4. **Example** — a realistic, everyday scenario showing this in practice\n\n"
        "Keep it practical and grounded, not generic motivation. Avoid spoilers unless the user asked for plot details.\n\n"
        "After the numbered points, end with a short '7-Day Application Plan' — one point per day for the first 7 points, "
        "with a brief daily micro-action."
    ),
    "main_plot": "Describe the main plot of the book '{book}' by {author}. Walk through the major events, turning points, and resolution in a clear narrative.",
    "suggestions": "Suggest 5 books similar to '{book}' by {author}. For each suggestion, explain briefly what it's about and why someone who enjoyed the original book would like it.",
}


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

        if not book_name or not author_name:
            error = "Please enter both a book name and author name."
        else:
            book_name = book_name.title()
            author_name = author_name.title()

            prompt_template = ACTIONS.get(selected_action, ACTIONS["summary"])
            prompt = prompt_template.format(book=book_name, author=author_name)

            if selected_action == "enrich_life_key_points":
                system_msg = (
                    "You are a knowledgeable and thoughtful book expert focused on practical life enrichment. "
                    "Be specific. Do not invent plot facts. If unsure, generalize responsibly and say so. "
                    "Use clear numbered formatting with bold labels."
                )
                max_tokens = 2048
            else:
                system_msg = (
                    "You are a knowledgeable and thoughtful book expert. "
                    "Provide well-written, engaging responses about books. Use clear paragraphs and formatting."
                )
                max_tokens = 1024

            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                error = "Server configuration error: API key not set."
            else:
                try:
                    client = anthropic.Anthropic(api_key=api_key)
                    message = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=max_tokens,
                        messages=[
                            {"role": "user", "content": prompt}
                        ],
                        system=system_msg,
                    )
                    result = message.content[0].text
                except anthropic.AuthenticationError:
                    error = "Invalid API key. Please check your configuration."
                except anthropic.RateLimitError:
                    error = "Rate limit reached. Please try again in a moment."
                except Exception as e:
                    error = f"Something went wrong: {str(e)}"

    return render_template(
        "index.html",
        result=result,
        error=error,
        book_name=book_name,
        author_name=author_name,
        selected_action=selected_action,
    )


@app.route("/api/suggest-book", methods=["POST"])
def suggest_book():
    data = request.get_json()
    description = (data.get("description") or "").strip()
    if not description:
        return jsonify({"error": "Please provide a description of the book."}), 400

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "Server configuration error: API key not set."}), 500

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"A user is trying to remember a book. Here is their description:\n\n"
                        f"\"{description}\"\n\n"
                        f"Identify the most likely book. Respond with ONLY valid JSON in this exact format:\n"
                        f'{{"title": "Book Title", "author": "Author Name", "confidence": "high/medium/low", '
                        f'"reasoning": "One sentence explaining why this matches"}}'
                    ),
                }
            ],
            system="You are a book identification expert. Always respond with valid JSON only, no other text.",
        )
        import json
        response_text = message.content[0].text.strip()
        result = json.loads(response_text)
        return jsonify(result)
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key."}), 401
    except anthropic.RateLimitError:
        return jsonify({"error": "Rate limit reached. Try again shortly."}), 429
    except (json.JSONDecodeError, KeyError):
        return jsonify({"error": "Could not identify the book. Try adding more details."}), 422
    except Exception as e:
        return jsonify({"error": f"Something went wrong: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
