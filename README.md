# MEDICAL CHATBOT

Meddy is a medical chatbot that collects your symptoms and recommends the most likely diseases, each with a description and precautions.

## Features

- **Symptom recognition (NLP):** Type a symptom in your own words (e.g. "my head hurts", "fever") and Meddy recognizes it using a PyTorch neural network trained on symptom intents.
- **Follow-up questions:** After each symptom, Meddy asks targeted yes/no questions ("Do you also have X?") to narrow down the disease faster, then gives the recommendation.
- **Combined recommendation:** Instead of a single disease name, Meddy ranks all diseases by probability and returns the **top 3 most likely diseases**, each with its description and precautions.
- **Scenario quick-reply buttons:** Pre-built symptom combinations (e.g. "Fever + Cough + Sore Throat") that return the recommendation in a single click, without typing each symptom separately.
- **PDF report:** A "Download report" button (file icon in the header) exports the last recommendation as a PDF you can show a doctor.
- **Chat history:** Every conversation is saved in a local SQLite database (`chat_history.db`) and replayed when you reopen the page. Use the trash icon in the header to clear it.
- **Voice typing:** Speak your symptoms (supported in Chrome/Edge) instead of typing.
- **Voice output:** The speaker icon in the header makes Meddy read replies aloud (Web Speech API).
- **Dark mode:** The moon icon toggles a dark theme, remembered between visits.
- **Severity warning:** If the entered symptoms are severe, Meddy reminds you to see a real doctor.

## How it works

The app uses two models:

- A **PyTorch neural network** (`nnet.py`, trained on `intents_short.json`) that maps a sentence to a symptom.
- A **scikit-learn stacking classifier** (`models/fitted_model.pickle2`, KNN + Logistic Regression + Decision Tree + SVM, trained in `Meddy.ipynb`) that predicts diseases from the set of symptoms. Its `predict_proba` output is used to rank the top 3 diseases.

Data files in `data/` provide symptom weights, disease descriptions and precautions.

## Requirements

Python 3.5 or newer.

Dependencies:

- Flask
- PyTorch
- NLTK
- NumPy
- Scikit-learn
- Pandas
- matplotlib

## Install requirements

Before running the application you need to install the dependencies. We recommend to use the virtual environment
[virtualenv](https://pypi.org/project/virtualenv/) for this.

Linux:

```
python3 -m venv venv
venv/bin/activate
pip install flask torch nltk numpy sklearn pandas matplotlib
```

Windows:

```
py -3 -m venv venv
venv\Scripts\activate
pip install flask torch nltk numpy==1.19.3 sklearn pandas matplotlib
```

In order for _nltk_ tokenization to work, the _'punkt'_ package must be downloaded. To do this, simply enter the Python shell and run the following:

```python
import nltk
nltk.download('punkt')
```

This will install all the required dependencies needed to run the application successfully.

## Run

To run MedicalChatbot, `cd` into the MedicalChatbot repo on your computer and run:

Linux:

```
venv/bin/python -m flask run
```

Windows (use backslashes in Command Prompt):

```
venv\Scripts\python -m flask run
```

This will run the Flask server in development mode on localhost, port 5000.

`* Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)`

Open http://127.0.0.1:5000/ in your browser.

> **Note:** if you get a "port already in use" error, an older server instance is still running. Stop it (Ctrl+C in its terminal, or `taskkill /F /PID <pid>` after finding it with `netstat -ano | findstr 5000`) and run the command again.

## How to use the chatbot

1. Type a symptom one at a time (e.g. "headache", then "fatigue") and press Enter or the send button. Meddy confirms each recognized symptom.
2. When you've entered all your symptoms, type **done** (or press the Start Over button). Meddy replies with the **top 3 most likely diseases**, each with its description and precautions, plus a doctor warning if the symptoms are severe.
3. Alternatively, click one of the **scenario buttons** above the input (e.g. "Fever + Cough + Sore Throat") to send a whole symptom combination at once and get the recommendation immediately.
4. Use **Start Over** to reset the conversation for a new session.

## API

### `POST /symptom`

Recognizes symptoms and predicts diseases. Accepts JSON.

**Single symptom (or the word "done"):**

```json
{ "sentence": "headache" }
```

- A symptom sentence returns a confirmation like `"Hmm, I'm 65.43% sure this is headache."`, adds it to the current session and asks a follow-up question ("Do you also have X? (yes/no)"). Answer yes/no to narrow down the disease.
- `"done"` returns the combined top-3 disease recommendation and resets the session.
- `"done"` with no symptoms entered returns a prompt to enter some symptoms first.
- An optional `"start_over": true` flag (used by the Start Over button) skips logging the message to chat history.

**Scenario (symptom combination in one request):**

```json
{ "symptoms": ["fever", "cough", "sore throat"] }
```

Returns the combined top-3 disease recommendation for the whole combination directly.

Both forms return a JSON string containing HTML (`<br>`, `<b>`, `<i>`) which the frontend renders in the chat.

### `GET /report`

Downloads the last recommendation as a PDF report (`meddy_report.pdf`).

### `GET/POST /clear_history`

Deletes all saved chat history.

### `GET /`

Renders the chat page (including replayed chat history), resets the current session and clears the follow-up question state.
