from flask import Flask, render_template, request
import openai
import os

app = Flask(__name__)

# OpenAI API Key (Add your key here)
client = openai.Client(api_key=os.getenv("OPENAI_API_KEY"))

@app.route('/', methods=['GET', 'POST'])
def home():
    result = ""
    book_name = ""
    author_name = ""
    if request.method == 'POST':
        book_name = request.form.get('book_name')
        author_name = request.form.get('author_name')
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

# index.html
html_code = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Book Summary Generator</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Poppins', sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background-color: #f4f4f9;
        }

        .container {
            background-color: #fff;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            max-width: 500px;
            width: 100%;
            text-align: center;
        }

        h1 {
            margin-bottom: 24px;
            font-size: 2rem;
            color: #333;
        }

        label {
            font-weight: 600;
            margin-bottom: 6px;
            display: block;
            text-align: left;
        }

        input, select, button {
            width: 100%;
            padding: 12px;
            margin: 12px 0;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 1rem;
        }

        button {
            background-color: #4CAF50;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: 600;
            transition: background-color 0.3s ease;
        }

        button:hover {
            background-color: #45a049;
        }

        .secondary-btn {
            background-color: #ddd;
            color: #333;
        }

        .secondary-btn:hover {
            background-color: #ccc;
        }

        #result {
            margin-top: 30px;
            padding: 20px;
            background-color: #e8f5e9;
            border: 1px solid #4CAF50;
            border-radius: 8px;
            text-align: left;
        }
    </style>
</head>
<body>

    <div class="container">
        <h1>📚 Book Summary Generator</h1>
        <form method="POST">
            <label for="book_name">Book Name:</label>
            <input type="text" id="book_name" name="book_name" required>

            <label for="author_name">Author Name:</label>
            <input type="text" id="author_name" name="author_name" required>

            <label for="action">Choose an Action:</label>
            <select id="action" name="action">
                <option value="summary">Make a summary</option>
                <option value="alternate_ending">Alternate ending</option>
                <option value="key_points">Key 5 Points</option>
                <option value="main_plot">Main Plot</option>
                <option value="suggestions">Suggest Similar Books</option>
            </select>

            <button type="submit">Get Result Now</button>
        </form>

        <button type="button" class="secondary-btn" id="newBookBtn">New Book</button>

        {% if result %}
        <div id="result">
            <h2>{{ book_name }} by {{ author_name }}</h2>
            <p style="white-space: pre-line;">{{ result }}</p>
        </div>
        {% endif %}
    </div>

    <script>
        document.getElementById('newBookBtn').onclick = function() {
            document.querySelector('form').reset();
            const resultDiv = document.getElementById('result');
            if (resultDiv) {
                resultDiv.style.display = 'none';
            }
        };
    </script>

</body>
</html>
'''
with open('templates/index.html', 'w') as f:
    f.write(html_code)
