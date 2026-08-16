import io
import json
import sqlite3
import torch
import nltk
import pickle
import random
from datetime import datetime
import numpy as np
import pandas as pd

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph

from nnet import NeuralNet
from nltk_utils import bag_of_words
from flask import Flask, render_template, url_for, request, jsonify, send_file

# nltk.word_tokenize needs the punkt_tab tokenizer data. Download it on
# startup if it's missing (e.g. on Render, where the environment is fresh).
for _nltk_resource in ("tokenizers/punkt_tab", "tokenizers/punkt"):
    try:
        nltk.data.find(_nltk_resource)
        break
    except LookupError:
        nltk.download(_nltk_resource.rsplit("/", 1)[-1])

random.seed(datetime.now().timestamp())

device = torch.device('cpu')
FILE = "models/data.pth"
model_data = torch.load(FILE, weights_only=False)

input_size = model_data['input_size']
hidden_size = model_data['hidden_size']
output_size = model_data['output_size']
all_words = model_data['all_words']
tags = model_data['tags']
model_state = model_data['model_state']

nlp_model = NeuralNet(input_size, hidden_size, output_size).to(device)
nlp_model.load_state_dict(model_state)
nlp_model.eval()

diseases_description = pd.read_csv("data/symptom_Description.csv")
diseases_description['Disease'] = diseases_description['Disease'].apply(lambda x: x.lower().strip(" "))

disease_precaution = pd.read_csv("data/symptom_precaution.csv")
disease_precaution['Disease'] = disease_precaution['Disease'].apply(lambda x: x.lower().strip(" "))

symptom_severity = pd.read_csv("data/Symptom-severity.csv")
symptom_severity = symptom_severity.map(lambda s: s.lower().strip(" ").replace(" ", "") if type(s) == str else s)


with open('data/list_of_symptoms.pickle', 'rb') as data_file:
    symptoms_list = pickle.load(data_file)

with open('models/fitted_model.pickle2', 'rb') as modelFile:
    prediction_model = pickle.load(modelFile)

# Map each disease to the symptoms that appear with it in the training data.
# Used to pick targeted follow-up questions.
dataset = pd.read_csv("data/dataset.csv")
symptom_set = set(symptoms_list)
disease_symptoms = {}
for _, row in dataset.iterrows():
    disease = str(row.iloc[0]).strip().lower()
    symptoms = disease_symptoms.setdefault(disease, set())
    for value in row.iloc[1:]:
        if pd.notna(value) and str(value).strip():
            symptoms.add(str(value).strip().replace(" ", ""))
for disease in disease_symptoms:
    disease_symptoms[disease] = {s for s in disease_symptoms[disease] if s in symptom_set}

# ---------------------------------------------------------------------------
# Chat history (SQLite)
# ---------------------------------------------------------------------------
DB_PATH = "chat_history.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "sender TEXT NOT NULL,"
        "text TEXT NOT NULL,"
        "created_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

def log_message(sender, text):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO messages (sender, text, created_at) VALUES (?, ?, ?)",
        (sender, text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()

def get_history(limit=200):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT sender, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [{"sender": r[0], "text": r[1]} for r in reversed(rows)]

def clear_history():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM messages")
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
user_symptoms = set()
followup_symptom = None      # symptom Meddy is currently asking about
followup_count = 0           # how many follow-up questions asked this session
followup_asked = set()       # symptoms already asked about, to avoid repeats
last_report_data = None      # last recommendation, used to build the PDF report

# How many most likely diseases to combine recommendations for when the user is done
TOP_N_DISEASES = 3
# How many follow-up questions Meddy may ask before giving a recommendation
MAX_FOLLOWUPS = 3

app = Flask(__name__)

def get_symptom(sentence):
    sentence = nltk.word_tokenize(sentence)
    X = bag_of_words(sentence, all_words)
    X = X.reshape(1, X.shape[0])
    X = torch.from_numpy(X)

    output = nlp_model(X)
    _, predicted = torch.max(output, dim=1)
    tag = tags[predicted.item()]

    probs = torch.softmax(output, dim=1)
    prob = probs[0][predicted.item()]
    prob = prob.item()

    return tag, prob

def is_done(text):
    return text.replace(".", "").replace("!", "").lower().strip() == "done"

def normalize_answer(text):
    return "".join(ch for ch in text.lower().replace("'", "").strip() if ch.isalnum() or ch.isspace()).strip()

def is_yes(text):
    return normalize_answer(text) in {
        "yes", "yeah", "yep", "yup", "sure", "correct", "right", "true",
        "of course", "definitely", "affirmative", "i do", "i have",
        "yes i do", "yes i have", "yes sure",
    }

def is_no(text):
    return normalize_answer(text) in {
        "no", "nope", "nah", "not", "false", "never", "negative",
        "not really", "i dont", "dont have", "no i dont", "no i dont have",
    }

def vectorize_symptoms():
    x_test = []
    for each in symptoms_list:
        x_test.append(1 if each in user_symptoms else 0)
    return np.asarray(x_test)

def reset_followup_state():
    global followup_symptom, followup_count
    followup_symptom = None
    followup_count = 0
    followup_asked.clear()

def pick_followup_symptom():
    """Picks a symptom that would help tell the top candidate diseases apart."""
    if not user_symptoms:
        return None
    probabilities = prediction_model.predict_proba(vectorize_symptoms().reshape(1, -1))[0]
    order = probabilities.argsort()[::-1][:3]
    top_keys = [prediction_model.classes_[i].strip().lower() for i in order]

    candidates = []
    for symptom in disease_symptoms.get(top_keys[0], set()):
        if symptom in user_symptoms or symptom in followup_asked:
            continue
        score = sum(
            (3 - i) for i, key in enumerate(top_keys)
            if symptom in disease_symptoms.get(key, set())
        )
        candidates.append((score, symptom))

    if not candidates:
        return None
    candidates.sort(key=lambda c: -c[0])
    return candidates[0][1]

def build_followup_question():
    """Returns a follow-up question to narrow down the disease, or None."""
    global followup_symptom, followup_count
    if followup_count >= MAX_FOLLOWUPS:
        return None
    symptom = pick_followup_symptom()
    if symptom is None:
        return None
    followup_symptom = symptom
    followup_asked.add(symptom)
    followup_count += 1
    return "Do you also have <b>" + symptom.replace("_", " ") + "</b>? (yes/no)"

def get_disease_recommendation():
    """Builds the combined recommendation for the currently collected symptoms.

    Ranks all diseases by probability and combines the description and
    precautions of the most likely ones, instead of recommending a single
    disease. Clears the collected symptoms when done.
    """
    global last_report_data

    probabilities = prediction_model.predict_proba(vectorize_symptoms().reshape(1, -1))[0]
    top_indices = probabilities.argsort()[::-1][:TOP_N_DISEASES]
    print([prediction_model.classes_[i] for i in top_indices])

    report_diseases = []
    recommendation_parts = []
    for idx in top_indices:
        disease = prediction_model.classes_[idx]
        probability = probabilities[idx]
        disease_key = disease.strip(" ").lower()

        description_rows = diseases_description.loc[diseases_description['Disease'] == disease_key, 'Description']
        precaution_rows = disease_precaution[disease_precaution['Disease'] == disease_key]

        # Skip diseases that have no description/precaution data on file
        if description_rows.empty or precaution_rows.empty:
            continue

        description = description_rows.iloc[0]
        precautions = ", ".join([
            precaution_rows.Precaution_1.iloc[0],
            precaution_rows.Precaution_2.iloc[0],
            precaution_rows.Precaution_3.iloc[0],
            precaution_rows.Precaution_4.iloc[0]
        ])

        report_diseases.append((disease.strip(), probability, description, precautions))
        recommendation_parts.append(
            "<b>" + disease.strip() + "</b> (" + f"{probability * 100:.1f}" + "% likely)<br>"
            + "<i>Description: " + description + "</i><br>"
            + "Precautions: " + precautions
        )

    last_report_data = {
        "symptoms": [s.replace("_", " ") for s in sorted(user_symptoms)],
        "diseases": report_diseases,
    }

    response_sentence = "It looks to me like you could have one of the following:<br><br>" \
        + "<br><br>".join(recommendation_parts)

    severity = []
    for each in user_symptoms:
        severity.append(symptom_severity.loc[symptom_severity['Symptom'] == each.lower().strip(" ").replace(" ", ""), 'weight'].iloc[0])

    if np.mean(severity) > 4 or np.max(severity) > 5:
        response_sentence = response_sentence + "<br><br>Considering your symptoms are severe, and Meddy isn't a real doctor, you should consider talking to one. :)"

    user_symptoms.clear()
    reset_followup_state()
    return response_sentence

def xml_escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

@app.route('/')
def index():
    data = []
    user_symptoms.clear()
    reset_followup_state()
    file = open("static/assets/files/ds_symptoms.txt", "r")
    all_symptoms = file.readlines()
    for s in all_symptoms:
        data.append(s.replace("'", "").replace("_", " ").replace(",\n", ""))
    data = json.dumps(data)

    return render_template('index.html', data=data, history=get_history())


@app.route('/symptom', methods=['GET', 'POST'])
def predict_symptom():
    global followup_symptom
    print("Request json:", request.json)
    data = request.json
    is_start_over = data.get('start_over', False)
    response_sentence = None
    user_text = None

    # Scenario request: a combination of symptoms sent at once,
    # answered directly with the disease recommendation.
    if 'symptoms' in data:
        user_text = ", ".join(data['symptoms'])
        for symptom_text in data['symptoms']:
            symptom, prob = get_symptom(symptom_text)
            if prob > .5:
                user_symptoms.add(symptom)

        if user_symptoms:
            response_sentence = get_disease_recommendation()
        else:
            response_sentence = random.choice(
                ["I'm sorry, but I don't understand those symptoms.",
                 "Meddy couldn't recognize any of those symptoms, please try again.",
                 "I didn't catch those symptoms, could you describe them differently?"])
    else:
        sentence = data['sentence']
        user_text = sentence

        if is_done(sentence):
            if not user_symptoms:
                response_sentence = random.choice(
                    ["I can't know what disease you may have if you don't enter any symptoms :)",
                     "Meddy can't know the disease if there are no symptoms...",
                     "You first have to enter some symptoms!"])
            else:
                response_sentence = get_disease_recommendation()

        elif followup_symptom is not None and (is_yes(sentence) or is_no(sentence)):
            # The user is answering a follow-up question
            pretty = followup_symptom.replace("_", " ")
            if is_yes(sentence):
                user_symptoms.add(followup_symptom)
                followup_symptom = None
                response_sentence = "Got it, I've noted <b>" + pretty + "</b>."
            else:
                followup_symptom = None
                response_sentence = "Okay, I'll leave <b>" + pretty + "</b> out."

            # Ask another question, or give the recommendation once we've asked enough
            question = build_followup_question()
            if question:
                response_sentence += "<br><br>" + question
            else:
                response_sentence += "<br><br>" + get_disease_recommendation()

        else:
            # New symptom (or something unrecognized)
            if followup_symptom is not None:
                followup_symptom = None  # user moved on, drop the pending question

            symptom, prob = get_symptom(sentence)
            print("Symptom:", symptom, ", prob:", prob)
            if prob > .5:
                user_symptoms.add(symptom)
                response_sentence = f"Hmm, I'm {(prob * 100):.2f}% sure this is " + symptom + "."
                question = build_followup_question()
                if question:
                    response_sentence += "<br><br>" + question
            else:
                response_sentence = "I'm sorry, but I don't understand you."

        print("User symptoms:", user_symptoms)

    if not is_start_over and response_sentence:
        log_message('user', user_text)
        log_message('bot', response_sentence)

    return jsonify(response_sentence.replace("_", " "))


@app.route('/report')
def report():
    """Downloads the last recommendation as a PDF report."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title="Meddy Medical Report")
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('MeddyTitle', parent=styles['Title'], spaceAfter=14)
    heading_style = ParagraphStyle('MeddyHeading', parent=styles['Heading2'], spaceBefore=14, spaceAfter=6)
    body_style = ParagraphStyle('MeddyBody', parent=styles['BodyText'], spaceAfter=6)

    story = [
        Paragraph("Meddy Medical Report", title_style),
        Paragraph("Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M"), body_style),
    ]

    report_data = last_report_data
    if not report_data or not report_data.get('diseases'):
        story.append(Paragraph(
            "No recommendation available yet. Enter your symptoms and ask Meddy for a diagnosis first.",
            body_style))
    else:
        story.append(Paragraph("Symptoms entered:", heading_style))
        for symptom in report_data['symptoms']:
            story.append(Paragraph("&#8226; " + xml_escape(symptom), body_style))

        story.append(Paragraph("Possible conditions:", heading_style))
        for disease, probability, description, precautions in report_data['diseases']:
            story.append(Paragraph(
                "<b>" + xml_escape(disease) + "</b> (" + f"{probability * 100:.1f}" + "% likely)",
                body_style))
            story.append(Paragraph("<b>Description:</b> " + xml_escape(description), body_style))
            story.append(Paragraph("<b>Precautions:</b> " + xml_escape(precautions), body_style))

    doc.build(story)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='meddy_report.pdf')


@app.route('/clear_history', methods=['GET', 'POST'])
def clear_history_route():
    clear_history()
    return jsonify({"status": "ok"})
