from flask import Flask, render_template, request
import anthropic
import os

app = Flask(__name__)

ACTIONS = {
    "summary": "Write a concise but insightful summary of the book '{book}' by {author}. Cover the main themes, plot, and key takeaways in a way that gives someone a solid understanding of the book.",
    "alternate_ending": "Imagine an alternate ending for the book '{book}' by {author}. Stay true to the characters and tone, but take the story in a different direction. Explain why this ending could also work.",
    "key_points": "List the 5 most important key points from the book '{book}' by {author}. For each point, provide a brief explanation of why it matters.",
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

            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                error = "Server configuration error: API key not set."
            else:
                try:
                    client = anthropic.Anthropic(api_key=api_key)
                    message = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=1024,
                        messages=[
                            {"role": "user", "content": prompt}
                        ],
                        system="You are a knowledgeable and thoughtful book expert. Provide well-written, engaging responses about books. Use clear paragraphs and formatting.",
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
