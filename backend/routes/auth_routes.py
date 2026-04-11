from flask import Blueprint, request, jsonify
from backend.auth import (
    hash_password, verify_password_any,
    create_token, require_auth, check_rate_limit,
)
from backend.database import get_db
from backend.config import ALLOWED_DOMAIN
import sqlite3
import re

auth_bp = Blueprint('auth', __name__)

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _validate_register(data: dict) -> str | None:
    """Return error string or None if valid."""
    name     = (data.get('name')     or '').strip()
    email    = (data.get('email')    or '').strip().lower()
    password =  data.get('password') or ''
    if not name:
        return 'Full name is required.'
    if len(name) > 100:
        return 'Name must be under 100 characters.'
    if not email or not _EMAIL_RE.match(email):
        return 'A valid email address is required.'
    if len(email) > 254:
        return 'Email address is too long.'
    if not email.endswith(f'@{ALLOWED_DOMAIN}'):
        return f'Only @{ALLOWED_DOMAIN} email addresses are allowed.'
    if len(password) < 8:
        return 'Password must be at least 8 characters.'
    if not re.search(r'[A-Z]', password):
        return 'Password must contain at least one uppercase letter.'
    if not re.search(r'[a-z]', password):
        return 'Password must contain at least one lowercase letter.'
    if not re.search(r'[0-9]', password):
        return 'Password must contain at least one number.'
    if not re.search(r'[^A-Za-z0-9]', password):
        return 'Password must contain at least one special character.'
    return None


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
            'INSERT INTO users (name, email, password_hash, company, role) '
            'VALUES (?,?,?,?,?)',
            (name, email, pw_hash, company, role),
        )
        conn.commit()
        user  = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        token = create_token(user['id'], user['role'])
        return jsonify({
            'token': token,
            'user': {
                'id':      user['id'],
                'name':    user['name'],
                'email':   user['email'],
                'role':    user['role'],
                'company': user['company'],
            },
        })
    except sqlite3.IntegrityError:
        return jsonify({'error': 'An account with this email already exists.'}), 409
    finally:
        conn.close()


@auth_bp.route('/api/login', methods=['POST'])
def login():
    ip = request.remote_addr
    if not check_rate_limit(ip):
        return jsonify({
            'error': 'Too many login attempts. Please wait 5 minutes.'
        }), 429

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
        'user': {
            'id':      user['id'],
            'name':    user['name'],
            'email':   user['email'],
            'role':    user['role'],
            'company': user['company'],
        },
    })


@auth_bp.route('/api/me', methods=['GET'])
@require_auth
def me():
    uid  = request.current_user['sub']
    conn = get_db()
    user = conn.execute(
        'SELECT id, name, email, role, company, created_at FROM users WHERE id=?',
        (uid,),
    ).fetchone()
    conn.close()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(dict(user))
