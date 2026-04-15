import hashlib
import re
import secrets
import smtplib
import logging
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import os

def send_reset_email(to_email, reset_link):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    print("SMTP_HOST:", smtp_host)
    print("SMTP_USER:", smtp_user)

    msg = MIMEMultipart()
    msg["Subject"] = "Reset Your Password — Chemsbury"
    msg["From"] = f"Chemsbury <{smtp_user}>"
    msg["To"] = to_email

    body = f"""
Hi,

Click the link below to reset your password:

{reset_link}

This link expires in 1 hour.
"""
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent")

    except Exception as e:
        print("❌ Email error:", str(e))

from flask import Blueprint, request, jsonify

from backend.auth import hash_password, verify_password_any, create_token, require_auth
from backend.database import get_db, rows_to_dicts
from backend import config

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


# ── VALIDATION ─────────────────────────────────

def _validate_register(data):
    name     = (data.get('name') or '').strip()
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not name:
        return 'Full name is required.'
    if not email or not _EMAIL_RE.match(email):
        return 'Valid email required.'
    #if not email.endswith(f"@{config.ALLOWED_DOMAIN}"):
        #return f'Only @{config.ALLOWED_DOMAIN} emails allowed.'
    if len(password) < 8:
        return 'Password must be at least 8 characters.'

    return None


# ── REGISTER ───────────────────────────────────

@auth_bp.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}

    err = _validate_register(data)
    if err:
        return jsonify({'error': err}), 400

    name    = data['name'].strip()
    email   = data['email'].strip().lower()
    company = (data.get('company') or '').strip()
    pw_hash = hash_password(data['password'])

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]

        role = 'admin' if count == 0 else 'user'

        cursor.execute(
            "INSERT INTO users (name, email, password_hash, company, role) VALUES (%s,%s,%s,%s,%s)",
            (name, email, pw_hash, company, role)
        )

        conn.commit()

        cursor.execute(
            "SELECT id, name, email, role, company FROM users WHERE email=%s",
            (email,)
        )

        rows = cursor.fetchall()
        user = rows_to_dicts(cursor, rows)[0]

        token = create_token(user['id'], user['role'])

        return jsonify({'token': token, 'user': user})

    except Exception as e:
        return jsonify({'error': str(e)}), 400

    finally:
        conn.close()


# ── LOGIN ──────────────────────────────────────

@auth_bp.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}

    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
    rows = cursor.fetchall()

    conn.close()

    if not rows:
        return jsonify({'error': 'Invalid credentials'}), 401

    user = rows_to_dicts(cursor, rows)[0]

    if not verify_password_any(password, user['password_hash']):
        return jsonify({'error': 'Invalid credentials'}), 401

    token = create_token(user['id'], user['role'])

    return jsonify({'token': token, 'user': user})


# ── GET CURRENT USER ────────────────────────────

@auth_bp.route('/api/me', methods=['GET'])
@require_auth
def me():
    uid = request.current_user['sub']

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, name, email, role, company, created_at FROM users WHERE id=%s",
        (uid,)
    )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return jsonify({'error': 'User not found'}), 404

    return jsonify(rows_to_dicts(cursor, rows)[0])


# ── FORGOT PASSWORD ─────────────────────────────

@auth_bp.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    if not email:
        return jsonify({'message': 'If registered, reset link sent'}), 200

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM users WHERE email=%s", (email,))
    rows = cursor.fetchall()
    rows = rows_to_dicts(cursor, rows)

    if rows:
        user = rows[0]

        cursor.execute("DELETE FROM password_resets WHERE user_id=%s", (user['id'],))

        raw_token = secrets.token_urlsafe(40)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.utcnow() + timedelta(hours=1)

        cursor.execute(
            "INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (%s,%s,%s)",
            (user['id'], token_hash, expires_at)
        )

        conn.commit()

        reset_url = f"{config.FRONTEND_URL}/reset-password?token={raw_token}"
        send_reset_email(email, reset_url)
        logger.warning(f"[DEV] Reset link: {reset_url}")

    conn.close()
    return jsonify({'message': 'If registered, reset link sent'}), 200


# ── RESET PASSWORD ──────────────────────────────

@auth_bp.route('/api/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json(silent=True) or {}

    raw_token = data.get('token')
    new_pass  = data.get('password')

    if not raw_token or not new_pass:
        return jsonify({'error': 'Invalid request'}), 400

    if len(new_pass) < 6:
        return jsonify({'error': 'Password too short'}), 400

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM password_resets WHERE token_hash=%s AND expires_at > NOW()",
        (token_hash,)
    )

    rows = cursor.fetchall()
    rows = rows_to_dicts(cursor, rows)

    if not rows:
        conn.close()
        return jsonify({'error': 'Invalid or expired token'}), 400

    row = rows[0]

    pw_hash = hash_password(new_pass)

    cursor.execute(
        "UPDATE users SET password_hash=%s WHERE id=%s",
        (pw_hash, row['user_id'])
    )

    cursor.execute(
        "DELETE FROM password_resets WHERE id=%s",
        (row['id'],)
    )

    conn.commit()
    conn.close()

    return jsonify({'message': 'Password reset successful'})

