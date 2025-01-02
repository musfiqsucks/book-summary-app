from flask import Flask, render_template, request
import openai
import os

app = Flask(__name__)

# Initialize OpenAI client
client = openai.Client(api_key=os.getenv("OPENAI_API_KEY"))

@app.route('/', methods=['GET', 'POST'])
def home():
    result = ""
    book_name = ""
    author_name = ""
    if request.method == 'POST':
        book_name = request.form.get('book_name').title()
        author_name = request.form.get('author_name').title()
        action = request.form.get('action')
        
        prompt = f"Write a {action} for the book '{book_name}' by {author_name}."
        
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant specialized in books."},
                    {"role": "user", "content": prompt}
                ]
            )
            result = response.choices[0].message.content.strip()
        except Exception as e:
            result = f"Error: {str(e)}"
    
    return render_template('index.html', result=result, book_name=book_name, author_name=author_name)

if __name__ == '__main__':
    app.run(debug=True)
