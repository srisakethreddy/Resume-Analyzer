from flask import Flask, render_template, request, redirect, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
import PyPDF2
import docx
import re
import string
from sentence_transformers import SentenceTransformer, util
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.graph_objects as go
import plotly.express as px
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.units import inch
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime
import json
from collections import Counter
import os

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

# ---------------- SPACY MODEL ----------------
nlp = None
try:
    import spacy
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        print("⚠️ spaCy model not found. Downloading...")
        os.system("python -m spacy download en_core_web_sm")
        nlp = spacy.load("en_core_web_sm")
except Exception as e:
    print(f"⚠️ spaCy initialization failed: {e}")
    print("📝 Using keyword-based extraction only (NER disabled)")
    nlp = None

# Configure matplotlib and seaborn
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

# Create instance folder for storing files
os.makedirs("instance", exist_ok=True)

# ---------------- SKILLS LIST ----------------
SKILLS_DB = [
    "python", "java", "c++", "sql", "javascript", "react", "node.js",
    "html", "css", "flask", "django", "aws", "docker", "kubernetes",
    "machine learning", "deep learning", "pandas", "numpy", "tensorflow",
    "pytorch", "git", "linux", "agile", "scrum", "excel", "power bi",
    "tableau", "c#", "spring", "rest api", "graphql"
]

def extract_skills(text):
    """Extract skills using both keyword matching and spaCy NER (if available)"""
    text_lower = text.lower()
    found_skills = set()
    
    # Keyword-based extraction
    for skill in SKILLS_DB:
        if skill in text_lower:
            found_skills.add(skill)
    
    # spaCy NER-based extraction for entity recognition (if available)
    if nlp is not None:
        try:
            doc = nlp(text[:10000])  # Limit to first 10000 chars for performance
            for ent in doc.ents:
                if ent.label_ in ["PRODUCT", "ORG"]:
                    skill_candidate = ent.text.lower().strip()
                    # Check if it matches common skill patterns
                    for skill in SKILLS_DB:
                        if skill in skill_candidate or skill_candidate in skill:
                            found_skills.add(skill)
        except Exception as e:
            print(f"⚠️ spaCy processing skipped: {e}")
    
    return list(found_skills)

# Helper function to get skill categories
def categorize_skills(skills):
    """Categorize skills by type"""
    categories = {
        "Programming Languages": ["python", "java", "c++", "c#", "javascript"],
        "Web Frameworks": ["flask", "django", "react", "node.js", "rest api", "graphql"],
        "Databases": ["sql"],
        "Cloud & DevOps": ["aws", "docker", "kubernetes", "linux"],
        "Data & ML": ["machine learning", "deep learning", "pandas", "numpy", "tensorflow", "pytorch"],
        "Web Technologies": ["html", "css"],
        "Tools & Methodologies": ["git", "agile", "scrum"],
        "Business Tools": ["excel", "power bi", "tableau", "spring"]
    }
    
    categorized = {cat: [] for cat in categories}
    uncategorized = []
    
    for skill in skills:
        found = False
        for category, skill_list in categories.items():
            if skill in skill_list:
                categorized[category].append(skill)
                found = True
                break
        if not found:
            uncategorized.append(skill)
    
    if uncategorized:
        categorized["Other"] = uncategorized
    
    # Remove empty categories
    return {k: v for k, v in categorized.items() if v}

# ---------------- SKILL MATCHING ----------------
def match_skills(resume_skills, jd_skills):
    matched = []
    for r_skill in resume_skills:
        for jd_skill in jd_skills:
            score = util.cos_sim(model.encode(r_skill), model.encode(jd_skill))
            if score >= 0.6:
                matched.append(r_skill)
    return list(set(matched))

# ============= VISUALIZATION FUNCTIONS =============

def create_skill_distribution_chart(all_skills, title="Skill Distribution"):
    """Create a bar chart for skill distribution"""
    if not all_skills:
        return None
    
    skill_counts = Counter(all_skills)
    top_n = min(15, len(skill_counts))
    top_skills = dict(skill_counts.most_common(top_n))
    
    fig = px.bar(
        x=list(top_skills.keys()),
        y=list(top_skills.values()),
        labels={'x': 'Skills', 'y': 'Frequency'},
        title=title,
        color=list(top_skills.values()),
        color_continuous_scale="Viridis"
    )
    fig.update_layout(xaxis_tickangle=-45, height=400)
    return fig

def create_pie_chart(skills_list, title="Skills Breakdown"):
    """Create a pie chart for skills breakdown"""
    if not skills_list:
        return None
    
    fig = px.pie(
        values=[1]*len(skills_list),
        names=skills_list,
        title=title,
        hole=0.3
    )
    return fig

def create_heatmap_skills(resume_skills, jd_skills):
    """Create a heatmap showing skill matches"""
    if not resume_skills or not jd_skills:
        return None
    
    # Create similarity matrix
    resume_skills_list = list(resume_skills)[:10]
    jd_skills_list = list(jd_skills)[:10]
    
    similarity_matrix = np.zeros((len(resume_skills_list), len(jd_skills_list)))
    
    for i, r_skill in enumerate(resume_skills_list):
        for j, jd_skill in enumerate(jd_skills_list):
            score = util.cos_sim(model.encode(r_skill), model.encode(jd_skill))
            similarity_matrix[i, j] = score.item()
    
    fig = go.Figure(data=go.Heatmap(
        z=similarity_matrix,
        x=jd_skills_list,
        y=resume_skills_list,
        colorscale="RdYlGn",
        zmin=0,
        zmax=1
    ))
    fig.update_layout(title="Skill Similarity Heatmap", height=400)
    return fig

def create_radar_chart(matched_count, resume_count, jd_count, total_unique):
    """Create a radar chart for match analysis"""
    categories = ['Matched', 'Resume Only', 'JD Only', 'Unmatched']
    values = [
        matched_count,
        max(0, resume_count - matched_count),
        max(0, jd_count - matched_count),
        max(0, total_unique - resume_count - jd_count)
    ]
    
    fig = go.Figure(data=go.Scatterpolar(
        r=values,
        theta=categories,
        fill='toself',
        name='Skills'
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, max(values)+1])),
        title="Skills Analysis Radar",
        height=400
    )
    return fig

def create_match_gauge(match_percentage):
    """Create a gauge chart showing match percentage"""
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=match_percentage,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': "Match Score"},
        delta={'reference': 50},
        gauge={
            'axis': {'range': [None, 100]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, 40], 'color': "lightgray"},
                {'range': [40, 70], 'color': "gray"},
                {'range': [70, 100], 'color': "lightgreen"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 90
            }
        }
    ))
    fig.update_layout(height=400)
    return fig

# ============= PDF REPORT GENERATION =============

def generate_pdf_report(candidate_name, email, phone, resume_skills, jd_skills, 
                        matched_skills, match_score, status, created_at=None):
    """Generate a comprehensive PDF analysis report"""
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=30,
        alignment=1
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#374151'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    # Title
    elements.append(Paragraph("ResumeAI Analysis Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Report date and candidate info
    timestamp = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    info_data = [
        ['Report Date:', timestamp],
        ['Candidate Name:', candidate_name],
        ['Email:', email],
        ['Phone:', phone]
    ]
    info_table = Table(info_data, colWidths=[2*inch, 4*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e5e7eb')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey)
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Match Score Summary
    elements.append(Paragraph("Match Summary", heading_style))
    match_data = [
        ['Metric', 'Value'],
        ['Match Score', f'{match_score}%'],
        ['Status', status],
        ['Matched Skills', str(len(matched_skills))],
        ['Resume Skills', str(len(resume_skills))],
        ['JD Skills', str(len(jd_skills))]
    ]
    match_table = Table(match_data, colWidths=[3*inch, 3*inch])
    match_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b82f6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f4f6')])
    ]))
    elements.append(match_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Skills Analysis
    elements.append(Paragraph("Skills Analysis", heading_style))
    
    # Resume Skills
    resume_skills_text = ', '.join(resume_skills[:15]) if resume_skills else 'None'
    if len(resume_skills) > 15:
        resume_skills_text += f', +{len(resume_skills) - 15} more'
    elements.append(Paragraph(f"<b>Resume Skills:</b> {resume_skills_text}", styles['Normal']))
    elements.append(Spacer(1, 0.1*inch))
    
    # JD Skills
    jd_skills_text = ', '.join(jd_skills[:15]) if jd_skills else 'None'
    if len(jd_skills) > 15:
        jd_skills_text += f', +{len(jd_skills) - 15} more'
    elements.append(Paragraph(f"<b>JD Required Skills:</b> {jd_skills_text}", styles['Normal']))
    elements.append(Spacer(1, 0.1*inch))
    
    # Matched Skills
    matched_skills_text = ', '.join(matched_skills) if matched_skills else 'None'
    elements.append(Paragraph(f"<b>Matched Skills:</b> {matched_skills_text}", styles['Normal']))
    elements.append(Spacer(1, 0.3*inch))
    
    # Recommendations
    elements.append(Paragraph("Recommendations", heading_style))
    if match_score >= 70:
        recommendation = "Excellent match! The candidate possesses most of the required skills for the position."
    elif match_score >= 50:
        recommendation = "Good match. The candidate has several required skills. Consider training in missing areas."
    elif match_score >= 40:
        recommendation = "Moderate match. The candidate has some relevant skills but lacks key requirements."
    else:
        recommendation = "Limited match. Significant skill gaps exist. Consider alternative candidates."
    
    elements.append(Paragraph(recommendation, styles['Normal']))
    elements.append(Spacer(1, 0.2*inch))
    
    # Footer
    elements.append(Paragraph(
        "<i>This report was generated by ResumeAI. For more information, contact the HR department.</i>",
        styles['Normal']
    ))
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer

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
        
        # Store in session for later use in analytics
        from flask import session as flask_session
        flask_session['analysis_data'] = {
            'name': name,
            'email': email_id,
            'phone': phone,
            'resume_skills': resume_skills,
            'jd_skills': jd_skills,
            'matched_skills': matched_skills,
            'score': score,
            'status': status
        }

    return render_template("dashboard.html", **context)

@app.route("/analytics")
@login_required
def analytics():
    """Display analytics and charts"""
    from flask import session as flask_session
    analysis_data = flask_session.get('analysis_data', {})
    
    if not analysis_data:
        return redirect("/dashboard")
    
    resume_skills = analysis_data.get('resume_skills', [])
    jd_skills = analysis_data.get('jd_skills', [])
    matched_skills = analysis_data.get('matched_skills', [])
    score = analysis_data.get('score', 0)
    
    # Generate charts
    bar_chart = create_skill_distribution_chart(
        resume_skills + jd_skills,
        "Skill Distribution"
    ).to_html(full_html=False, include_plotlyjs='cdn') if resume_skills or jd_skills else None
    
    pie_resume = create_pie_chart(
        resume_skills,
        "Resume Skills"
    ).to_html(full_html=False, include_plotlyjs='cdn') if resume_skills else None
    
    pie_jd = create_pie_chart(
        jd_skills,
        "Required JD Skills"
    ).to_html(full_html=False, include_plotlyjs='cdn') if jd_skills else None
    
    heatmap = create_heatmap_skills(
        resume_skills,
        jd_skills
    ).to_html(full_html=False, include_plotlyjs='cdn') if resume_skills and jd_skills else None
    
    radar = create_radar_chart(
        len(matched_skills),
        len(resume_skills),
        len(jd_skills),
        len(set(resume_skills + jd_skills))
    ).to_html(full_html=False, include_plotlyjs='cdn')
    
    gauge = create_match_gauge(score).to_html(full_html=False, include_plotlyjs='cdn')
    
    context = {
        'analysis_data': analysis_data,
        'bar_chart': bar_chart,
        'pie_resume': pie_resume,
        'pie_jd': pie_jd,
        'heatmap': heatmap,
        'radar': radar,
        'gauge': gauge
    }
    
    return render_template("analytics.html", **context)

@app.route("/export_pdf")
@login_required
def export_pdf():
    """Export analysis report as PDF"""
    from flask import session as flask_session
    analysis_data = flask_session.get('analysis_data', {})
    
    if not analysis_data:
        return redirect("/dashboard")
    
    pdf_buffer = generate_pdf_report(
        candidate_name=analysis_data.get('name', 'Unknown'),
        email=analysis_data.get('email', 'N/A'),
        phone=analysis_data.get('phone', 'N/A'),
        resume_skills=analysis_data.get('resume_skills', []),
        jd_skills=analysis_data.get('jd_skills', []),
        matched_skills=analysis_data.get('matched_skills', []),
        match_score=analysis_data.get('score', 0),
        status=analysis_data.get('status', 'Unknown')
    )
    
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"ResumeAI_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    )

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