import hashlib
import re
import secrets
import sqlite3
import smtplib
import logging
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Blueprint, request, jsonify

from backend.auth import hash_password, verify_password_any, create_token, require_auth, check_rate_limit
from backend.database import get_db
from backend import config   # ✅ FIXED IMPORT

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


# ── Validation ────────────────────────────────────────────────────────────────
def _validate_register(data: dict) -> str | None:
    name     = (data.get('name')     or '').strip()
    email    = (data.get('email')    or '').strip().lower()
    password =  data.get('password') or ''
    if not name:                                   return 'Full name is required.'
    if len(name) > 100:                            return 'Name must be under 100 characters.'
    if not email or not _EMAIL_RE.match(email):    return 'A valid email address is required.'
    if len(email) > 254:                           return 'Email address is too long.'
    if not email.endswith(f'@{config.ALLOWED_DOMAIN}'):   return f'Only @{config.ALLOWED_DOMAIN} email addresses are allowed.'
    if len(password) < 8:                          return 'Password must be at least 8 characters.'
    if not re.search(r'[A-Z]', password):          return 'Password must contain at least one uppercase letter.'
    if not re.search(r'[a-z]', password):          return 'Password must contain at least one lowercase letter.'
    if not re.search(r'[0-9]', password):          return 'Password must contain at least one number.'
    if not re.search(r'[^A-Za-z0-9]', password):  return 'Password must contain at least one special character.'
    return None


# ── Register ──────────────────────────────────────────────────────────────────
@auth_bp.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    err  = _validate_register(data)
    if err:
        return jsonify({'error': err}), 400

    name    = data['name'].strip()[:100]
    email   = data['email'].strip().lower()[:254]
    company = (data.get('company') or '').strip()[:200]
    pw_hash = hash_password(data['password'])

    conn = get_db()
    try:
        count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        role  = 'admin' if count == 0 else 'user'
        conn.execute(
            'INSERT INTO users (name, email, password_hash, company, role) VALUES (?,?,?,?,?)',
            (name, email, pw_hash, company, role),
        )
        conn.commit()
        user  = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        token = create_token(user['id'], user['role'])
        return jsonify({
            'token': token,
            'user': {'id': user['id'], 'name': user['name'], 'email': user['email'],
                     'role': user['role'], 'company': user['company']},
        })
    except sqlite3.IntegrityError:
        return jsonify({'error': 'An account with this email already exists.'}), 409
    finally:
        conn.close()


# ── Login ─────────────────────────────────────────────────────────────────────
@auth_bp.route('/api/login', methods=['POST'])
def login():
    ip = request.remote_addr
    if not check_rate_limit(ip):
        return jsonify({'error': 'Too many login attempts. Please wait 5 minutes.'}), 429

    data     = request.get_json(silent=True) or {}
    email    = (data.get('email')    or '').strip().lower()[:254]
    password =  data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Email and password are required.'}), 400

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    conn.close()

    if not user or not verify_password_any(password, user['password_hash']):
        return jsonify({'error': 'Invalid email or password.'}), 401

    token = create_token(user['id'], user['role'])
    return jsonify({
        'token': token,
        'user': {'id': user['id'], 'name': user['name'], 'email': user['email'],
                 'role': user['role'], 'company': user['company']},
    })


# ── Me ────────────────────────────────────────────────────────────────────────
@auth_bp.route('/api/me', methods=['GET'])
@require_auth
def me():
    uid  = request.current_user['sub']
    conn = get_db()
    user = conn.execute(
        'SELECT id, name, email, role, company, created_at FROM users WHERE id=?', (uid,)
    ).fetchone()
    conn.close()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(dict(user))


# ── Forgot Password ───────────────────────────────────────────────────────────
@auth_bp.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    """
    Generate a reset token and email it (or log it if no SMTP configured).
    Always returns 200 to avoid user enumeration.
    """
    data  = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    if not email or not _EMAIL_RE.match(email):
        return jsonify({'message': 'If that address is registered, a reset link has been sent.'}), 200

    conn = get_db()
    user = conn.execute('SELECT id, name FROM users WHERE email=?', (email,)).fetchone()

    if user:
        # Expire old tokens
        conn.execute(
            "DELETE FROM password_resets WHERE user_id=? OR expires_at < datetime('now')",
            (user['id'],)
        )

        raw_token  = secrets.token_urlsafe(40)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()

        conn.execute(
            'INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (?,?,?)',
            (user['id'], token_hash, expires_at)
        )
        conn.commit()

        reset_url = f"{config.FRONTEND_URL}/reset-password?token={raw_token}"
        _send_reset_email(email, user['name'], reset_url)

    conn.close()
    return jsonify({'message': 'If that address is registered, a reset link has been sent.'}), 200


# ── Reset Password ────────────────────────────────────────────────────────────
@auth_bp.route('/api/reset-password', methods=['POST'])
def reset_password():
    data      = request.get_json(silent=True) or {}
    raw_token = (data.get('token') or '').strip()
    new_pass  = data.get('password') or ''

    if not raw_token:
        return jsonify({'error': 'Reset token is required.'}), 400
    if len(new_pass) < 8:
        return jsonify({'error': 'Password must be at least 8 characters.'}), 400
    if not re.search(r'[A-Z]', new_pass):
        return jsonify({'error': 'Password must contain at least one uppercase letter.'}), 400
    if not re.search(r'[0-9]', new_pass):
        return jsonify({'error': 'Password must contain at least one number.'}), 400
    if not re.search(r'[^A-Za-z0-9]', new_pass):
        return jsonify({'error': 'Password must contain at least one special character.'}), 400

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    conn       = get_db()
    row        = conn.execute(
        "SELECT * FROM password_resets WHERE token_hash=? AND used=0 AND expires_at > datetime('now')",
        (token_hash,)
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({'error': 'Reset link is invalid or has expired. Please request a new one.'}), 400

    pw_hash = hash_password(new_pass)
    conn.execute('UPDATE users SET password_hash=? WHERE id=?', (pw_hash, row['user_id']))
    conn.execute('UPDATE password_resets SET used=1 WHERE id=?', (row['id'],))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Password updated successfully. You can now sign in.'})


# ── Email helper ──────────────────────────────────────────────────────────────
def _send_reset_email(to_email: str, name: str, reset_url: str):
    if not config.SMTP_HOST:
        # No SMTP configured — log for development
        logger.warning(f"[DEV] Password reset link for {to_email}: {reset_url}")
        return

    subject = "Reset your Chemsbury password"
    body_html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f4f7fb;padding:40px 0;">
      <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;
                  overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <div style="background:linear-gradient(135deg,#0a5f7a,#3ecfcf);padding:28px 32px;">
          <h1 style="color:#fff;font-size:1.4rem;margin:0;">Chemsbury Solutions</h1>
          <p style="color:rgba(255,255,255,0.8);margin:6px 0 0;font-size:0.9rem;">Water Quality Analysis Platform</p>
        </div>
        <div style="padding:32px;">
          <p style="color:#333;font-size:1rem;">Hi {name},</p>
          <p style="color:#555;line-height:1.6;">
            We received a request to reset the password for your Chemsbury account.
            Click the button below to set a new password. This link expires in <strong>1 hour</strong>.
          </p>
          <div style="text-align:center;margin:28px 0;">
            <a href="{reset_url}" style="background:linear-gradient(135deg,#3ecfcf,#5b9cf6);
               color:#0a0f1a;font-weight:700;font-size:0.95rem;padding:13px 32px;
               border-radius:8px;text-decoration:none;display:inline-block;">
              Reset Password
            </a>
          </div>
          <p style="color:#888;font-size:0.82rem;line-height:1.5;">
            If you didn't request this, you can safely ignore this email.
            Your password will not change until you click the link above.<br><br>
            If the button doesn't work, copy this URL:<br>
            <span style="word-break:break-all;color:#3ecfcf;">{reset_url}</span>
          </p>
        </div>
        <div style="padding:16px 32px;background:#f9fafb;border-top:1px solid #eee;
                    font-size:0.75rem;color:#aaa;text-align:center;">
          Chemsbury Environmental Solutions · chemsbury.in
        </div>
      </div>
    </body></html>
    """

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = config.SMTP_FROM
        msg['To']      = to_email
        msg.attach(MIMEText(body_html, 'html'))

        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_FROM, [to_email], msg.as_string())
        logger.info(f"Reset email sent to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send reset email to {to_email}: {e}")
