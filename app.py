from flask import Flask, render_template, request, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
import PyPDF2
import docx
import re
import string
from sentence_transformers import SentenceTransformer, util

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ---------------- DATABASE ----------------
class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

# ---------------- TEXT EXTRACTION ----------------
def extract_text_from_pdf(file):
    reader = PyPDF2.PdfReader(file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text.lower()

def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join([p.text for p in doc.paragraphs]).lower()

def extract_email(text):
    match = re.search(r"\S+@\S+", text)
    return match.group(0) if match else "Not Found"

def extract_phone(text):
    match = re.search(r"\+?\d[\d -]{8,12}\d", text)
    return match.group(0) if match else "Not Found"

def extract_name(text):
    lines = text.split("\n")
    for line in lines[:10]:
        words = line.strip().split()
        if 1 < len(words) <= 3 and all(word.isalpha() for word in words):
            return line.strip().title()
    return "Not Found"

# ---------------- CLEANING ----------------
def clean_text(text):
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    words = text.split()
    words = [word for word in words if len(word) > 2]
    return " ".join(words)

# ---------------- WORD MATCH FUNCTION ----------------
def calculate_match(resume_text, jd_text):
    resume_words = set(resume_text.split())
    jd_words = set(jd_text.split())
    if not jd_words:
        return 0
    matched = resume_words.intersection(jd_words)
    percentage = (len(matched) / len(jd_words)) * 100
    return round(percentage, 2)

# ---------------- BERT MODEL ----------------
model = SentenceTransformer('all-MiniLM-L6-v2')

# ---------------- SKILLS LIST ----------------
SKILLS_DB = [
    "python", "java", "c++", "sql", "javascript", "react", "node.js",
    "html", "css", "flask", "django", "aws", "docker", "kubernetes",
    "machine learning", "deep learning", "pandas", "numpy", "tensorflow",
    "pytorch", "git", "linux", "agile", "scrum", "excel", "power bi",
    "tableau", "c#", "spring", "rest api", "graphql"
]

def extract_skills(text):
    text = text.lower()
    found_skills = set()
    for skill in SKILLS_DB:
        if skill in text:
            found_skills.add(skill)
    return list(found_skills)

# ---------------- SKILL MATCHING ----------------
def match_skills(resume_skills, jd_skills):
    matched = []
    for r_skill in resume_skills:
        for jd_skill in jd_skills:
            score = util.cos_sim(model.encode(r_skill), model.encode(jd_skill))
            if score >= 0.6:
                matched.append(r_skill)
    return list(set(matched))

# ---------------- ROUTES ----------------
@app.route("/")
def login():
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login_post():
    email = request.form.get("email")
    password = request.form.get("password")

    if not email or not password:
        return render_template("login.html", error="Please fill all fields")

    user = Admin.query.filter_by(email=email).first()

    if not user:
        return render_template("login.html", error="Email not found")

    if not check_password_hash(user.password, password):
        return render_template("login.html", error="Incorrect password")

    login_user(user)
    return redirect("/dashboard")

@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    context = {}
    if request.method == "POST":
        jd_file = request.files["jd_file"]
        resume_file = request.files["resume_file"]

        # ---- JD TEXT ----
        filename = jd_file.filename.lower()
        if filename.endswith(".pdf"):
            jd_text = extract_text_from_pdf(jd_file)
        elif filename.endswith(".docx"):
            jd_text = extract_text_from_docx(jd_file)
        elif filename.endswith(".txt"):
            jd_text = jd_file.read().decode("utf-8").lower()
        else:
            jd_text = ""

        # ---- RESUME TEXT ----
        filename_r = resume_file.filename.lower()
        if filename_r.endswith(".pdf"):
            resume_text = extract_text_from_pdf(resume_file)
        elif filename_r.endswith(".docx"):
            resume_text = extract_text_from_docx(resume_file)
        elif filename_r.endswith(".txt"):
            resume_text = resume_file.read().decode("utf-8").lower()
        else:
            resume_text = ""

        # ---- CLEAN TEXT ----
        resume_clean = clean_text(resume_text)
        jd_clean = clean_text(jd_text)

        # ---- Extract candidate info ----
        name = extract_name(resume_text)
        email_id = extract_email(resume_text)
        phone = extract_phone(resume_text)

        # ---- Extract real skills ----
        resume_skills = extract_skills(resume_text)
        jd_skills = extract_skills(jd_text)
        matched_skills = match_skills(resume_skills, jd_skills)

        # ---- Match score ----
        score = calculate_match(resume_clean, jd_clean)
        status = "Eligible" if score >= 40 else "Not Eligible"

        context.update({
            "resume_clean": resume_clean,
            "jd_clean": jd_clean,
            "resume_skills": resume_skills,
            "jd_skills": jd_skills,
            "matched_skills": matched_skills,
            "score": score,
            "status": status,
            "name": name,
            "email": email_id,
            "phone": phone
        })

    return render_template("dashboard.html", **context)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")

# ---------------- INIT ----------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        if not Admin.query.first():
            admin = Admin(
                email="admin@gmail.com",
                password=generate_password_hash("admin123")
            )
            db.session.add(admin)
            db.session.commit()
    app.run(debug=True)