import os
import io
import uuid
import hashlib
import sqlite3
import pdfplumber
import requests
import streamlit as st
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import google.generativeai as genai
from groq import Groq

# =============================
# ENVIRONMENT SETUP
# =============================
from dotenv import load_dotenv
load_dotenv()

gemini_api_key = os.getenv("GEMINI_API_KEY")
ocr_api_key = os.getenv("OCR_SPACE_API_KEY")
groq_api_key = os.getenv("GROQ_API_KEY")

if gemini_api_key:
    genai.configure(api_key=gemini_api_key)

groq_client = Groq(api_key=groq_api_key) if (groq_api_key and Groq) else None

st.set_page_config(page_title="AI Legal Assistant", page_icon="⚖", layout="wide")

# =============================
# LEGAL QUESTION VALIDATION
# =============================
def is_legal_question(question):
    """
    Check if the question is related to legal matters
    Returns True if legal, False if not legal
    """
    if not question or len(question.strip()) < 3:
        return False
    
    question_lower = question.lower().strip()
    
    # Legal keywords - comprehensive list
    legal_keywords = [
        # Basic legal terms
        'law', 'legal', 'court', 'judge', 'lawyer', 'attorney', 'advocate',
        'case', 'lawsuit', 'litigation', 'trial', 'hearing', 'verdict',
        
        # Contract related
        'contract', 'agreement', 'breach', 'terms', 'clause', 'violation',
        'binding', 'negotiation', 'dispute', 'settlement',
        
        # Criminal law
        'criminal', 'crime', 'arrest', 'police', 'bail', 'prison', 'jail',
        'theft', 'fraud', 'assault', 'murder', 'robbery', 'evidence',
        'investigation', 'charges', 'guilty', 'innocent', 'conviction',
        
        # Civil law
        'civil', 'plaintiff', 'defendant', 'damages', 'compensation',
        'negligence', 'liability', 'tort', 'injury', 'accident',
        
        # Property law
        'property', 'real estate', 'land', 'ownership', 'title', 'deed',
        'mortgage', 'lease', 'rent', 'tenant', 'landlord', 'eviction',
        
        # Family law
        'divorce', 'marriage', 'custody', 'alimony', 'adoption', 'inheritance',
        'will', 'estate', 'guardian', 'family court',
        
        # Business law
        'corporation', 'company', 'business', 'partnership', 'tax',
        'intellectual property', 'patent', 'trademark', 'copyright',
        'employment', 'workplace', 'discrimination', 'harassment',
        
        # Legal procedures
        'summon', 'notice', 'petition', 'motion', 'appeal', 'jurisdiction',
        'statute', 'regulation', 'ordinance', 'constitution', 'rights',
        'obligation', 'duty', 'penalty', 'fine', 'sentence',
        
        # Indian legal terms
        'ipc', 'crpc', 'cpc', 'indian penal code', 'high court', 'supreme court',
        'sessions court', 'magistrate', 'fir', 'chargesheet', 'bail',
        'anticipatory bail', 'interim order', 'stay order', 'injunction',
        
        # Common legal phrases
        'legal advice', 'legal help', 'legal issue', 'legal problem',
        'legal matter', 'legal question', 'legal rights', 'legal action',
        'legal proceeding', 'legal document', 'legal compliance',
        
        # Question starters that are usually legal
        'can i sue', 'is it legal', 'what are my rights', 'legal procedure',
        'court process', 'how to file', 'legal requirement', 'violation of'
    ]
    
    # Legal question patterns
    legal_patterns = [
        'what is the law', 'according to law', 'legally speaking',
        'court order', 'legal document', 'file a case', 'legal action',
        'my rights', 'legal procedure', 'court hearing', 'legal advice'
    ]
    
    # Check for legal keywords
    for keyword in legal_keywords:
        if keyword in question_lower:
            return True
    
    # Check for legal patterns
    for pattern in legal_patterns:
        if pattern in question_lower:
            return True
    
    # Additional checks for common legal question formats
    legal_question_starts = [
        'can i legally', 'is it illegal', 'what does the law say',
        'according to indian law', 'under which section', 'legal validity',
        'court procedure', 'how to file', 'legal notice', 'summon received'
    ]
    
    for start in legal_question_starts:
        if question_lower.startswith(start):
            return True
    
    return False

def get_non_legal_response():
    """
    Returns a polite message for non-legal questions
    """
    return """
🚫 **Please ask a legal question.**

I'm designed to help with legal matters such as:
- Legal advice and procedures
- Court cases and documentation  
- Contract and agreement issues
- Rights and obligations
- Legal compliance matters
- Indian law and regulations

Please rephrase your question to focus on legal topics.

"""

# =============================
# SECURITY + DATABASE (unchanged)
# =============================
def make_hash(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  password TEXT,
                  role TEXT,
                  email TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  role TEXT,
                  conversation_id TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                  is_user_message BOOLEAN,
                  message TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  case_number TEXT,
                  client_email TEXT,
                  lawyer_email TEXT,
                  deadline_date TEXT,
                  message TEXT,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def register_user(username, password, role, email=None):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, role, email) VALUES (?, ?, ?, ?)",
                  (username, make_hash(password), role, email))
        conn.commit()
        st.success("✅ Registration successful! Please login.")
    except sqlite3.IntegrityError:
        st.error("⚠ Username already exists")
    conn.close()

def login_user(username, password):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT role, email FROM users WHERE username=? AND password=?",
              (username, make_hash(password)))
    result = c.fetchone()
    conn.close()
    return result if result else None

def save_chat_message(username, role, conversation_id, is_user_message, message):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("INSERT INTO history (username, role, conversation_id, is_user_message, message) VALUES (?, ?, ?, ?, ?)",
              (username, role, conversation_id, is_user_message, str(message)))
    conn.commit()
    conn.close()

# --- Conversation Titles (first user question per conversation) ---
def load_conversation_titles(username):
    """
    Return list of tuples (conversation_id, first_user_message_excerpt)
    Ordered by latest conversation first.
    """
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    # Get earliest user message per conversation (MIN timestamp) then fetch its message.
    c.execute("""
        SELECT h.conversation_id, h.message, h.timestamp
        FROM history h
        INNER JOIN (
            SELECT conversation_id, MIN(timestamp) AS first_ts
            FROM history
            WHERE username=? AND is_user_message=1
            GROUP BY conversation_id
        ) firsts
        ON h.conversation_id = firsts.conversation_id AND h.timestamp = firsts.first_ts
        WHERE h.username=? AND h.is_user_message=1
        ORDER BY firsts.first_ts DESC
    """, (username, username))
    rows = c.fetchall()
    conn.close()
    titles = []
    for cid, msg, ts in rows:
        excerpt = (msg[:45] + "...") if msg and len(msg) > 45 else (msg or "User message")
        titles.append((cid, excerpt))
    return titles

def load_messages_by_conversation_id(conversation_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT is_user_message, message FROM history WHERE conversation_id=? ORDER BY timestamp ASC", (conversation_id,))
    messages = [{"role": "user" if row[0] else "assistant", "content": row[1]} for row in c.fetchall()]
    conn.close()
    return messages

# --- Reminder DB functions ---
def save_case_reminder(case_number, client_email, lawyer_email, deadline_date, message):
    try:
        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        c.execute("INSERT INTO reminders (case_number, client_email, lawyer_email, deadline_date, message) VALUES (?, ?, ?, ?, ?)",
                  (case_number, client_email, lawyer_email, deadline_date.strftime("%Y-%m-%d"), message))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("save_case_reminder error:", e)
        return False

def get_all_reminders():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT id, case_number, client_email, lawyer_email, deadline_date, message, created_at FROM reminders ORDER BY deadline_date ASC")
    reminders = c.fetchall()
    conn.close()
    return reminders

def delete_reminder(reminder_id):
    try:
        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        c.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("delete_reminder error:", e)
        return False

# --- Email send helper (simulated if no SMTP creds) ---
def send_email(to_email, subject, body):
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))

    if not sender_email or not sender_password:
        # Simulation (prints + saves locally)
        print("📧 EMAIL SIMULATION")
        print("TO:", to_email)
        print("SUBJECT:", subject)
        print("BODY:\n", body)
        save_email_details(to_email, subject, body)
        return True

    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()

        save_email_details(to_email, subject, body)
        return True
    except Exception as e:
        print("send_email error:", e)
        save_email_details(to_email, subject, body)
        # Return False only if you want to treat failure; keeping True for demo as earlier behavior
        return True

def save_email_details(to_email, subject, body):
    with open("sent_emails.txt", "a", encoding="utf-8") as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"TO: {to_email}\n")
        f.write(f"SUBJECT: {subject}\n")
        f.write(f"BODY:\n{body}\n")
        f.write(f"TIME: {datetime.now()}\n")
        f.write(f"{'='*50}\n")

def send_reminder_emails(case_number, client_email, lawyer_email, deadline_date, reminder_message=""):
    deadline_str = deadline_date.strftime("%B %d, %Y")
    client_subject = f"📅 Case {case_number} - Deadline Reminder"
    client_body = f"""Dear Client,

This is a reminder regarding your case:

📋 Case Number: {case_number}
📅 Deadline: {deadline_str}

{f'📝 Additional Message: {reminder_message}' if reminder_message else ''}

Please ensure all required documents and actions are completed before the deadline.

Best regards,
Legal Assistant System
"""
    lawyer_subject = f"⚖ Case {case_number} - Deadline Reminder"
    lawyer_body = f"""Dear Lawyer,

This is a reminder regarding case:

📋 Case Number: {case_number}
📅 Deadline: {deadline_str}
👤 Client: {client_email}

{f'📝 Additional Message: {reminder_message}' if reminder_message else ''}

Please ensure all case preparations are completed before the deadline.

Best regards,
Legal Assistant System
"""
    client_sent = send_email(client_email, client_subject, client_body)
    lawyer_sent = send_email(lawyer_email, lawyer_subject, lawyer_body)
    return client_sent and lawyer_sent

# =============================
# UTILITIES (unchanged)
# =============================
def generate_pdf(text: str) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 50, "AI Legal Assistant - Report")
    c.setFont("Helvetica", 11)
    y = height - 80
    for line in str(text).split("\n"):
        c.drawString(50, y, line[:1000])
        y -= 15
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = height - 50
    c.save()
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data

def ocr_pdf_with_ocr_space(file):
    response = requests.post(
        "https://api.ocr.space/parse/image",
        files={"file": file},
        data={"apikey": ocr_api_key, "OCREngine": 2, "language": "eng"}
    )
    result = response.json()
    text = ""
    for parsed in result.get("ParsedResults", []):
        text += parsed.get("ParsedText", "") + "\n"
    return text

def extract_text_from_pdf(file):
    text = ""
    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        # if no text (scanned PDF) and ocr key available
        if not text.strip() and ocr_api_key:
            file.seek(0)
            text = ocr_pdf_with_ocr_space(file)
    except Exception as e:
        st.error(f"Error reading PDF: {e}")
    return text

def ask_groq(question, context_text):
    if not groq_client:
        return None
    for m in ["llama-3.1-70b-specdec", "llama-3.1-8b-instant"]:
        try:
            response = groq_client.chat.completions.create(
                model=m,
                messages=[
                    {"role": "system", "content": "You are a helpful legal assistant."},
                    {"role": "user", "content": f"Document:\n{context_text}\n\nQuestion:\n{question}"}
                ],
                temperature=0.2,
                max_tokens=800
            )
            return response.choices[0].message.content
        except Exception:
            continue
    return None

# =============================
# MAIN APP
# =============================
init_db()
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["role"] = None
    st.session_state["username"] = None
    st.session_state["user_email"] = None
    st.session_state["messages"] = []
    st.session_state["current_conversation_id"] = None
    st.session_state["show_reminder_form"] = False
    st.session_state["show_reminders"] = False

# -----------------------------
# Step 1: Role selection
# -----------------------------
if not st.session_state["logged_in"]:
    if not st.session_state["role"]:
        st.markdown("""
        <style>
        .centered { display: flex; justify-content: center; align-items: center; flex-direction: column; height: 80vh; }
        .profiles { display: flex; gap: 80px; justify-content: center; margin-top: 30px; }
        .profile-btn { width: 180px; height: 180px; border-radius: 50%; border: 3px solid #444; background: linear-gradient(145deg, #2e2e2e, #1b1b1b); color: white; font-size: 22px; font-weight: bold; cursor: pointer; transition: all 0.3s; display: flex; flex-direction: column; justify-content: center; align-items: center; box-shadow: 0px 4px 10px rgba(0,0,0,0.4); }
        .profile-btn:hover { transform: scale(1.1); border-color: #fff; }
        .emoji { font-size: 45px; margin-bottom: 10px; }
        </style>
        <div class="centered">
            <h1>⚖ Welcome to AI Legal Assistant</h1>
            <p>Select your role to continue:</p>
            <div class="profiles">
                <a href="?role=lawyer" class="profile-btn"><div class="emoji">👨‍⚖</div> Lawyer</a>
                <a href="?role=civilian" class="profile-btn"><div class="emoji">👩‍💼</div> Civilian</a>
            </div>
        </div>
        """, unsafe_allow_html=True)
        if "role" in st.query_params:
            st.session_state["role"] = st.query_params["role"]
            st.rerun()
    else:
        st.subheader(f"🔐 {st.session_state['role'].capitalize()} Login / Register")
        choice = st.radio("Choose an option:", ["Login", "Register"])
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if choice == "Register":
            email = st.text_input("Email")
            if st.button("Register") and username and password:
                register_user(username, password, st.session_state["role"], email)
        else:
            if st.button("Login") and username and password:
                result = login_user(username, password)
                if result and result[0] == st.session_state["role"]:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = username
                    st.session_state["user_email"] = result[1] if result[1] else ""
                    st.session_state["current_conversation_id"] = str(uuid.uuid4())
                    st.rerun()
                else:
                    st.error("❌ Invalid username/password or role")

# -----------------------------
# Step 2: Logged in dashboard
# -----------------------------
else:
    # Sidebar
    with st.sidebar:
        st.header(f"👋 Welcome, {st.session_state['username']} ({st.session_state['role']})")

        # --- New Chat ---
        if st.button("✨ New Chat"):
            st.session_state["messages"] = []
            st.session_state["current_conversation_id"] = str(uuid.uuid4())
            st.rerun()

        # --- Conversation History (show first user question as title) ---
        st.markdown("### 💬 Conversation History")
        history_list = load_conversation_titles(st.session_state["username"])
        if history_list:
            for cid, title in history_list:
                if st.button(f"🗂 {title}", key=f"history_{cid}"):
                    st.session_state["current_conversation_id"] = cid
                    st.session_state["messages"] = load_messages_by_conversation_id(cid)
                    st.rerun()
        else:
            st.info("No history yet.")

        # --- Logout ---
        if st.button("🚪 Logout"):
            st.session_state.clear()
            st.rerun()

    # ================= Lawyer Dashboard =================
    if st.session_state["role"] == "lawyer":
        st.title("👨‍⚖ Lawyer Panel")
        # --- Lawyer-only reminders controls ---
        if st.session_state["role"] == "lawyer":
            st.markdown("---")
            if st.button("🔔 Set Reminder"):
                st.session_state["show_reminder_form"] = True
                st.session_state["show_reminders"] = False

        # --- PDF Upload & Analysis ---
        st.subheader("📂 Upload Summon/Notice PDF")
        
        uploaded_file = st.file_uploader("Upload Summon/Notice PDF", type=["pdf"])
        if uploaded_file:
            with st.spinner("Extracting text..."):
                text = extract_text_from_pdf(uploaded_file)
                if text.strip():
                    st.success("✅ Text extracted successfully!")
                    st.text_area("Extracted Text", text, height=250)
                    if st.button("🔍 Analyze Document"):
                        with st.spinner("Analyzing with AI..."):
                            result = ask_groq("Analyze this legal document", text)
                            if result:
                                st.markdown("### 📑 AI Analysis")
                                st.write(result)
                                st.download_button("⬇ Download Report (PDF)", data=generate_pdf(result), file_name="legal_analysis.pdf", mime="application/pdf")
                            else:
                                st.error("❌ Could not analyze document.")

        # --- Chat with Legal Validation ---
        st.subheader("💬 Chat with AI")
        if st.session_state.get("messages"):
            for msg in st.session_state["messages"]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        if user_input := st.chat_input("Ask about legal summons or notices..."):
            # Ensure conversation id exists
            if not st.session_state.get("current_conversation_id"):
                st.session_state["current_conversation_id"] = str(uuid.uuid4())
            
            st.session_state["messages"].append({"role": "user", "content": user_input})
            save_chat_message(st.session_state["username"], st.session_state["role"], st.session_state["current_conversation_id"], True, user_input)
            
            with st.chat_message("user"):
                st.markdown(user_input)

            with st.chat_message("assistant"):
                with st.spinner("Analyzing..."):
                    # 🔥 LEGAL VALIDATION CHECK
                    if is_legal_question(user_input):
                        # Legal question - proceed normally
                        answer = ask_groq(user_input, "Legal context")
                        if not answer:
                            answer = "Sorry, I couldn't process this legal question right now."
                    else:
                        # Non-legal question - show validation message
                        answer = get_non_legal_response()
                    
                    st.markdown(answer)
                    st.session_state["messages"].append({"role": "assistant", "content": answer})
                    save_chat_message(st.session_state["username"], st.session_state["role"], st.session_state["current_conversation_id"], False, answer)

        # --- Reminder form ---
        if st.session_state.get("show_reminder_form", False):
            st.markdown("#### 📝 Create Case Reminder")
            with st.form("reminder_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    case_number = st.text_input("Case Number *", placeholder="Enter case number")
                    client_email = st.text_input("Client Email *", placeholder="client@example.com")
                    lawyer_email = st.text_input("Lawyer Email *", value=st.session_state.get("user_email", ""), placeholder="lawyer@example.com")
                with col2:
                    deadline_date = st.date_input("Deadline Date *", min_value=datetime.now().date())
                    reminder_message = st.text_area("Reminder Message", placeholder="Optional custom message", height=100)
                col1, col2, col3 = st.columns([1, 1, 1])
                with col2:
                    submit_reminder = st.form_submit_button("💾 Save & Send Reminder", type="primary", use_container_width=True)
                with col3:
                    cancel_reminder = st.form_submit_button("❌ Cancel", use_container_width=True)
            if submit_reminder:
                if case_number and client_email and lawyer_email and deadline_date:
                    success = save_case_reminder(case_number, client_email, lawyer_email, deadline_date, reminder_message)
                    if success:
                        email_sent = send_reminder_emails(case_number, client_email, lawyer_email, deadline_date, reminder_message)
                        if email_sent:
                            st.success("📧 Reminder saved & emails sent (or simulated).")
                            st.session_state["show_reminder_form"] = False
                        else:
                            st.error("❌ Failed to send reminder emails (check SMTP settings).")
                    else:
                        st.error("❌ Failed to save reminder.")
                else:
                    st.warning("⚠ Please fill in all required fields.")
            if cancel_reminder:
                st.session_state["show_reminder_form"] = False

    # ================= Civilian Dashboard =================
    elif st.session_state["role"] == "civilian":
        st.title("👩‍💼 Civilian Legal Assistant")

        # --- Chat with Legal Validation ---
        st.subheader("💬 Chat with AI")
        if st.session_state.get("messages"):
            for msg in st.session_state["messages"]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        if user_input := st.chat_input("Ask your legal question..."):
            if not st.session_state.get("current_conversation_id"):
                st.session_state["current_conversation_id"] = str(uuid.uuid4())
            
            st.session_state["messages"].append({"role": "user", "content": user_input})
            save_chat_message(st.session_state["username"], st.session_state["role"], st.session_state["current_conversation_id"], True, user_input)
            
            with st.chat_message("user"):
                st.markdown(user_input)

            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    # 🔥 LEGAL VALIDATION CHECK
                    if is_legal_question(user_input):
                        # Legal question - proceed normally
                        answer = ask_groq(user_input, "Civilian legal context")
                        if not answer:
                            answer = "Sorry, I couldn't process this legal question right now."
                    else:
                        # Non-legal question - show validation message
                        answer = get_non_legal_response()
                    
                    st.markdown(answer)
                    st.session_state["messages"].append({"role": "assistant", "content": answer})
                    save_chat_message(st.session_state["username"], st.session_state["role"], st.session_state["current_conversation_id"], False, answer)