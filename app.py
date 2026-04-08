from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from functools import wraps
import pdfplumber
import base64 as _b64
import base64
import io
import re
import os
import tempfile
import sqlite3
import json
import hashlib
import hmac
import time
import secrets
from datetime import datetime
from PIL import Image
import cv2
import numpy as np

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static')
CORS(app, origins="*")

PORT = int(os.environ.get('PORT', 3000))
MAX_FILE_SIZE_MB = 10
ALLOWED_DOMAIN = 'chemsbury.in'
JWT_SECRET = os.environ.get('JWT_SECRET', secrets.token_hex(32))
DB_PATH = os.environ.get('DB_PATH', 'chemsbury.db')

# ─── IS:10500 DEFAULT PARAMETERS ─────────────────────────────────────────────
# (parameter_name, unit, permissible_limit, acceptable_limit, hi_is_bad, lo_limit, lo_is_bad)
# hi_is_bad=1 means value > permissible_limit is bad
# lo_is_bad=1 means value < lo_limit is bad
IS10500_DEFAULTS = [
    ('ph',          '',      8.5,   6.5,  1, 6.5,  1),
    ('turbidity',   'NTU',   5.0,   1.0,  1, None, 0),
    ('tds',         'mg/L',  500.0, 500.0,1, None, 0),
    ('hardness',    'mg/L',  300.0, 200.0,1, None, 0),
    ('iron',        'mg/L',  0.3,   0.1,  1, None, 0),
    ('chloride',    'mg/L',  250.0, 250.0,1, None, 0),
    ('fluoride',    'mg/L',  1.5,   1.0,  1, None, 0),
    ('nitrate',     'mg/L',  45.0,  45.0, 1, None, 0),
    ('manganese',   'mg/L',  0.1,   0.05, 1, None, 0),
    ('alkalinity',  'mg/L',  200.0, 200.0,1, None, 0),
    ('sulphate',    'mg/L',  200.0, 200.0,1, None, 0),
    ('calcium',     'mg/L',  75.0,  75.0, 1, None, 0),
    ('magnesium',   'mg/L',  30.0,  30.0, 1, None, 0),
    ('copper',      'mg/L',  0.05,  0.05, 1, None, 0),
    ('zinc',        'mg/L',  5.0,   5.0,  1, None, 0),
    ('arsenic',     'mg/L',  0.01,  0.01, 1, None, 0),
    ('lead',        'mg/L',  0.01,  0.01, 1, None, 0),
    ('chromium',    'mg/L',  0.05,  0.05, 1, None, 0),
    ('aluminium',   'mg/L',  0.1,   0.03, 1, None, 0),
    ('ammonia',     'mg/L',  0.5,   0.5,  1, None, 0),
    ('h2s',         'mg/L',  0.05,  0.05, 1, None, 0),
    ('boron',       'mg/L',  1.0,   1.0,  1, None, 0),
    ('nitrite',     'mg/L',  0.02,  0.02, 1, None, 0),
    ('phenol',      'mg/L',  0.001, 0.001,1, None, 0),
    ('coliform',    'MPN/100mL', 0.0, 0.0,1, None, 0),
    ('ecoli',       'MPN/100mL', 0.0, 0.0,1, None, 0),
    ('tss',         'mg/L',  10.0,  10.0, 1, None, 0),
    ('bod',         'mg/L',  2.0,   2.0,  1, None, 0),
    ('cod',         'mg/L',  10.0,  10.0, 1, None, 0),
    ('colour',      'Hazen', 15.0,  5.0,  1, None, 0),
]

# ─── DATABASE ────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            company TEXT,
            role TEXT DEFAULT 'user',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            lab_info TEXT,
            sample_info TEXT,
            params TEXT,
            safety_status TEXT,
            method_used TEXT,
            confidence TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS water_parameters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parameter_name TEXT NOT NULL UNIQUE,
            unit TEXT,
            permissible_limit REAL,
            acceptable_limit REAL,
            hi_is_bad INTEGER DEFAULT 1,
            lo_limit REAL,
            lo_is_bad INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            updated_at TEXT,
            updated_by INTEGER REFERENCES users(id)
        );
    ''')
    conn.commit()

    # Seed defaults only if table is empty
    count = conn.execute('SELECT COUNT(*) FROM water_parameters').fetchone()[0]
    if count == 0:
        conn.executemany(
            '''INSERT OR IGNORE INTO water_parameters
               (parameter_name, unit, permissible_limit, acceptable_limit, hi_is_bad, lo_limit, lo_is_bad)
               VALUES (?,?,?,?,?,?,?)''',
            IS10500_DEFAULTS
        )
        conn.commit()
        logger.info(f"Seeded {len(IS10500_DEFAULTS)} IS:10500 parameters into water_parameters table.")

    conn.close()
    logger.info("Database initialised.")

init_db()

# ─── PASSWORD HASHING ────────────────────────────────────────────────────────
def hash_password(password):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000)
    return f"{salt}:{h.hex()}"

def verify_password(password, stored):
    try:
        salt, h = stored.split(':')
        h2 = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000)
        return hmac.compare_digest(h, h2.hex())
    except Exception:
        return False

# ─── JWT ─────────────────────────────────────────────────────────────────────
def _b64url(data):
    if isinstance(data, str):
        data = data.encode()
    return _b64.urlsafe_b64encode(data).rstrip(b'=').decode()

def _b64url_decode(s):
    s += '=' * (-len(s) % 4)
    return _b64.urlsafe_b64decode(s)

def create_token(user_id, role):
    header = _b64url(json.dumps({'alg':'HS256','typ':'JWT'}))
    payload = _b64url(json.dumps({
        'sub': user_id,
        'role': role,
        'exp': int(time.time()) + 86400
    }))
    sig_input = f"{header}.{payload}".encode()
    sig = hmac.new(JWT_SECRET.encode(), sig_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"

def verify_token(token):
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header, payload, sig = parts
        sig_input = f"{header}.{payload}".encode()
        expected = hmac.new(JWT_SECRET.encode(), sig_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(sig), expected):
            return None
        data = json.loads(_b64url_decode(payload))
        if data.get('exp', 0) < int(time.time()):
            return None
        return data
    except Exception:
        return None

def get_current_user():
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:]
        data = verify_token(token)
        if data:
            return data
    return None

def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorised'}), 401
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper

def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorised'}), 401
        if user.get('role') != 'admin':
            return jsonify({'error': 'Forbidden'}), 403
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper

# ─── EasyOCR (lazy load) ─────────────────────────────────────────────────────
_ocr = None
def get_ocr():
    global _ocr
    if _ocr is None:
        import easyocr
        _ocr = easyocr.Reader(['en'], gpu=False, verbose=False)
    return _ocr

# ─── Parameter key mapping ────────────────────────────────────────────────────
PARAM_MAP = {
    'colour': ['colour', 'color'],
    'turbidity': ['turbidity'],
    'ph': ['ph @', 'ph@', 'ph '],
    'hardness': ['total hardness', 'hardness'],
    'iron': ['iron as fe', 'iron'],
    'chloride': ['chloride as cl', 'chloride'],
    'tds': ['total dissolved solids', 'tds'],
    'calcium': ['calcium as ca', 'calcium'],
    'magnesium': ['magnesium as mg', 'magnesium'],
    'copper': ['copper as cu', 'copper'],
    'manganese': ['manganese as mn', 'manganese'],
    'sulphate': ['sulphate as so4', 'sulphate', 'sulfate'],
    'nitrate': ['nitrate as no3', 'nitrate'],
    'alkalinity': ['total alkalinity', 'alkalinity'],
    'boron': ['boron as b', 'boron'],
    'arsenic': ['arsenic as as', 'arsenic'],
    'h2s': ['sulphide as h2s', 'h2s', 'sulphide', 'sulfide'],
    'fluoride': ['fluoride as f', 'fluoride'],
    'zinc': ['zinc as zn', 'zinc'],
    'aluminium': ['aluminium as al', 'aluminium', 'aluminum'],
    'ammonia': ['ammonia as total ammonia', 'ammonia'],
    'coliform': ['coliforms', 'total coliforms', 'coliform'],
    'ecoli': ['e.coli', 'e. coli', 'ecoli'],
    'chromium': ['chromium as cr', 'chromium'],
    'phenol': ['phenolic compounds', 'phenol'],
    'tss': ['total suspended solids', 'tss'],
    'bod': ['biochemical oxygen demand', 'bod'],
    'cod': ['chemical oxygen demand', 'cod'],
    'lead': ['lead as pb', 'lead'],
    'nitrite': ['nitrite as no2', 'nitrite'],
}

def match_param_key(text):
    t = text.lower().strip()
    for key, aliases in PARAM_MAP.items():
        for alias in aliases:
            if alias in t:
                return key
    return None

def parse_value(text):
    if not text:
        return None
    t = text.strip().lower()
    if any(x in t for x in ['bdl', 'below detectable', 'absent', 'not detected', 'nil', 'nd']):
        return 0.0
    match = re.search(r'\d+\.?\d*', text)
    if match:
        return float(match.group())
    return None

def preprocess_image(img):
    img_np = np.array(img)
    h, w = img_np.shape[:2]
    if w < 1800:
        scale = 1800 / w
        img_np = cv2.resize(img_np, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, h=10)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    gray = cv2.filter2D(gray, -1, kernel)
    gray = cv2.equalizeHist(gray)
    return Image.fromarray(cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB))

def extract_with_pdfplumber(pdf_bytes):
    params = {}
    sample_info = ""
    lab_info = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 3:
                        continue
                    param_text = str(row[1] or '').strip()
                    result_text = str(row[2] or '').strip()
                    key = match_param_key(param_text)
                    if key:
                        val = parse_value(result_text)
                        if val is not None:
                            params[key] = val
            text = page.extract_text() or ''
            if not sample_info:
                for line in text.splitlines():
                    ll = line.lower()
                    if any(x in ll for x in ['sample', 'location', 'source', 'ref no', 'report no']):
                        sample_info = line.strip()
                        break
            if not lab_info:
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                if lines:
                    lab_info = lines[0]
    return params, sample_info, lab_info

def extract_with_easyocr(image_bytes):
    ocr = get_ocr()
    params = {}
    sample_info = ""
    lab_info = ""
    img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    img = preprocess_image(img)
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        img.save(tmp.name, 'PNG')
        tmp_path = tmp.name
    try:
        result = ocr.readtext(tmp_path, detail=1, paragraph=False, width_ths=0.7, height_ths=0.7)
    finally:
        os.unlink(tmp_path)
    if not result:
        return params, sample_info, lab_info
    lines = []
    for (bbox, text, conf) in result:
        x_center = (bbox[0][0] + bbox[2][0]) / 2
        y_center = (bbox[0][1] + bbox[2][1]) / 2
        lines.append({'text': text, 'x': x_center, 'y': y_center, 'conf': conf})
    lines.sort(key=lambda l: l['y'])
    if lines:
        lab_info = lines[0]['text']
    rows = []
    current_row = []
    last_y = None
    for l in lines:
        if last_y is None or abs(l['y'] - last_y) < 18:
            current_row.append(l)
        else:
            if current_row:
                rows.append(sorted(current_row, key=lambda x: x['x']))
            current_row = [l]
        last_y = l['y']
    if current_row:
        rows.append(sorted(current_row, key=lambda x: x['x']))
    for row in rows:
        if len(row) < 2:
            continue
        texts = [c['text'] for c in row]
        if len(texts) >= 3:
            key = match_param_key(texts[1])
            if key:
                val = parse_value(texts[2])
                if val is not None:
                    params[key] = val
                continue
        key = match_param_key(texts[0])
        if key:
            val = parse_value(texts[1])
            if val is not None:
                params[key] = val
    for l in lines:
        ll = l['text'].lower()
        if any(x in ll for x in ['sample', 'location', 'source', 'ref no']):
            sample_info = l['text']
            break
    return params, sample_info, lab_info

# ─── DYNAMIC SAFETY ASSESSMENT (reads from DB) ───────────────────────────────
def get_limits_from_db():
    """
    Returns a dict: { parameter_name: {permissible_limit, acceptable_limit,
                                        hi_is_bad, lo_limit, lo_is_bad} }
    Only active parameters are returned.
    Falls back to hardcoded IS:10500 defaults if DB is unavailable.
    """
    try:
        conn = get_db()
        rows = conn.execute(
            'SELECT * FROM water_parameters WHERE is_active=1'
        ).fetchall()
        conn.close()
        limits = {}
        for row in rows:
            limits[row['parameter_name']] = {
                'permissible_limit': row['permissible_limit'],
                'acceptable_limit':  row['acceptable_limit'],
                'hi_is_bad':         row['hi_is_bad'],
                'lo_limit':          row['lo_limit'],
                'lo_is_bad':         row['lo_is_bad'],
            }
        return limits
    except Exception as e:
        logger.warning(f"Could not load limits from DB, using fallback: {e}")
        # Hardcoded fallback
        return {
            'ph':         {'permissible_limit':8.5,'acceptable_limit':6.5,'hi_is_bad':1,'lo_limit':6.5,'lo_is_bad':1},
            'tds':        {'permissible_limit':500,'acceptable_limit':500,'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'iron':       {'permissible_limit':0.3,'acceptable_limit':0.1,'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'hardness':   {'permissible_limit':300,'acceptable_limit':200,'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'chloride':   {'permissible_limit':250,'acceptable_limit':250,'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'turbidity':  {'permissible_limit':5,  'acceptable_limit':1,  'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'h2s':        {'permissible_limit':0.05,'acceptable_limit':0.05,'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'nitrate':    {'permissible_limit':45, 'acceptable_limit':45, 'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'manganese':  {'permissible_limit':0.1,'acceptable_limit':0.05,'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'fluoride':   {'permissible_limit':1.5,'acceptable_limit':1.0,'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'alkalinity': {'permissible_limit':200,'acceptable_limit':200,'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'coliform':   {'permissible_limit':0,  'acceptable_limit':0,  'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'arsenic':    {'permissible_limit':0.01,'acceptable_limit':0.01,'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'lead':       {'permissible_limit':0.01,'acceptable_limit':0.01,'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
            'ecoli':      {'permissible_limit':0,  'acceptable_limit':0,  'hi_is_bad':1,'lo_limit':None,'lo_is_bad':0},
        }

def compute_safety_status(params):
    """
    Reads limits dynamically from DB.
    Logic:
      - unsafe  → value > permissible_limit * 1.5  OR  value < lo_limit (when lo_is_bad)
      - caution → value > permissible_limit
      - safe    → all within limits
    """
    limits = get_limits_from_db()
    overall = 'safe'
    for param_name, limit_data in limits.items():
        v = params.get(param_name)
        if v is None:
            continue
        perm  = limit_data.get('permissible_limit')
        lo    = limit_data.get('lo_limit')
        hi_bad = limit_data.get('hi_is_bad', 1)
        lo_bad = limit_data.get('lo_is_bad', 0)

        if hi_bad and perm is not None:
            if v > perm * 1.5:
                return 'unsafe'          # immediate unsafe — no need to check further
            if v > perm and overall == 'safe':
                overall = 'caution'

        if lo_bad and lo is not None:
            if v < lo:
                return 'unsafe'

    return overall

# ─── AUTH API ─────────────────────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    company = (data.get('company') or '').strip()

    if not name or not email or not password:
        return jsonify({'error': 'Name, email and password are required.'}), 400
    if not email.endswith(f'@{ALLOWED_DOMAIN}'):
        return jsonify({'error': f'Only @{ALLOWED_DOMAIN} email addresses are allowed.'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters.'}), 400
    # 2. Uppercase Check
    if not re.search(r'[A-Z]', password):
        return jsonify({'error': 'Password must contain at least one uppercase letter.'}), 400
    # 3. Lowercase Check
    if not re.search(r'[a-z]', password):
        return jsonify({'error': 'Password must contain at least one lowercase letter.'}), 400
    # 4. Number Check
    if not re.search(r'\d', password):
        return jsonify({'error': 'Password must contain at least one number.'}), 400
    # 5. Special Symbol Check
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return jsonify({'error': 'Password must contain at least one special symbol.'}), 400

    conn = get_db()
    try:
        count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        role = 'admin' if count == 0 else 'user'
        pw_hash = hash_password(password)
        conn.execute(
            'INSERT INTO users (name, email, password_hash, company, role) VALUES (?,?,?,?,?)',
            (name, email, pw_hash, company, role)
        )
        conn.commit()
        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        token = create_token(user['id'], user['role'])
        return jsonify({
            'token': token,
            'user': {'id': user['id'], 'name': user['name'], 'email': user['email'],
                     'role': user['role'], 'company': user['company']}
        })
    except sqlite3.IntegrityError:
        return jsonify({'error': 'An account with this email already exists.'}), 409
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'Email and password are required.'}), 400
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    conn.close()
    if not user or not verify_password(password, user['password_hash']):
        return jsonify({'error': 'Invalid email or password.'}), 401
    token = create_token(user['id'], user['role'])
    return jsonify({
        'token': token,
        'user': {'id': user['id'], 'name': user['name'], 'email': user['email'],
                 'role': user['role'], 'company': user['company']}
    })

@app.route('/api/me', methods=['GET'])
@require_auth
def api_me():
    uid = request.current_user['sub']
    conn = get_db()
    user = conn.execute('SELECT id,name,email,role,company,created_at FROM users WHERE id=?', (uid,)).fetchone()
    conn.close()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(dict(user))

# ─── ANALYSES API ─────────────────────────────────────────────────────────────
@app.route('/api/analyses', methods=['GET'])
@require_auth
def api_analyses():
    uid = request.current_user['sub']
    conn = get_db()
    rows = conn.execute(
        'SELECT id,lab_info,sample_info,safety_status,method_used,confidence,created_at FROM analyses WHERE user_id=? ORDER BY created_at DESC',
        (uid,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/analyses/<int:aid>', methods=['GET'])
@require_auth
def api_analysis_detail(aid):
    uid = request.current_user['sub']
    role = request.current_user.get('role')
    conn = get_db()
    row = conn.execute('SELECT * FROM analyses WHERE id=?', (aid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    if row['user_id'] != uid and role != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    d = dict(row)
    if d.get('params'):
        d['params'] = json.loads(d['params'])
    return jsonify(d)

# ─── ADMIN API ────────────────────────────────────────────────────────────────
@app.route('/api/admin/users', methods=['GET'])
@require_admin
def api_admin_users():
    conn = get_db()
    users = conn.execute(
        '''SELECT u.id, u.name, u.email, u.company, u.role, u.created_at,
           COUNT(a.id) as analysis_count
           FROM users u LEFT JOIN analyses a ON a.user_id=u.id
           GROUP BY u.id ORDER BY u.created_at DESC'''
    ).fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route('/api/admin/analyses', methods=['GET'])
@require_admin
def api_admin_analyses():
    conn = get_db()
    rows = conn.execute(
        '''SELECT a.id, a.user_id, a.lab_info, a.sample_info, a.safety_status, a.method_used,
           a.confidence, a.created_at, u.name as user_name, u.email as user_email
           FROM analyses a JOIN users u ON u.id=a.user_id
           ORDER BY a.created_at DESC LIMIT 200'''
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/users/<int:uid>/role', methods=['PUT'])
@require_admin
def api_admin_set_role(uid):
    data = request.get_json()
    role = data.get('role')
    if role not in ('user', 'admin'):
        return jsonify({'error': 'Invalid role'}), 400
    conn = get_db()
    conn.execute('UPDATE users SET role=? WHERE id=?', (role, uid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/users/<int:uid>', methods=['DELETE'])
@require_admin
def api_admin_delete_user(uid):
    me_id = request.current_user['sub']
    if uid == me_id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    conn = get_db()
    conn.execute('DELETE FROM analyses WHERE user_id=?', (uid,))
    conn.execute('DELETE FROM users WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ─── WATER PARAMETERS API ────────────────────────────────────────────────────

@app.route('/api/admin/parameters', methods=['GET'])
@require_admin
def api_get_parameters():
    """Return all water parameters (active and inactive)."""
    conn = get_db()
    rows = conn.execute(
        '''SELECT wp.*, u.name as updated_by_name
           FROM water_parameters wp
           LEFT JOIN users u ON u.id = wp.updated_by
           ORDER BY wp.parameter_name ASC'''
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/parameters/<int:pid>', methods=['PUT'])
@require_admin
def api_update_parameter(pid):
    """Update a water parameter's limits or active status."""
    data = request.get_json()
    allowed_fields = ['unit', 'permissible_limit', 'acceptable_limit',
                      'hi_is_bad', 'lo_limit', 'lo_is_bad', 'is_active']
    updates = {k: v for k, v in data.items() if k in allowed_fields}
    if not updates:
        return jsonify({'error': 'No valid fields to update'}), 400

    uid = request.current_user['sub']
    updates['updated_at'] = datetime.utcnow().isoformat()
    updates['updated_by'] = uid

    set_clause = ', '.join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [pid]

    conn = get_db()
    conn.execute(f'UPDATE water_parameters SET {set_clause} WHERE id=?', values)
    conn.commit()
    row = conn.execute(
        'SELECT wp.*, u.name as updated_by_name FROM water_parameters wp LEFT JOIN users u ON u.id=wp.updated_by WHERE wp.id=?',
        (pid,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Parameter not found'}), 404
    return jsonify(dict(row))

@app.route('/api/admin/parameters', methods=['POST'])
@require_admin
def api_add_parameter():
    """Add a new water parameter."""
    data = request.get_json()
    name = (data.get('parameter_name') or '').strip().lower()
    if not name:
        return jsonify({'error': 'parameter_name is required'}), 400

    uid = request.current_user['sub']
    conn = get_db()
    try:
        conn.execute(
            '''INSERT INTO water_parameters
               (parameter_name, unit, permissible_limit, acceptable_limit,
                hi_is_bad, lo_limit, lo_is_bad, updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            (
                name,
                data.get('unit', ''),
                data.get('permissible_limit'),
                data.get('acceptable_limit'),
                data.get('hi_is_bad', 1),
                data.get('lo_limit'),
                data.get('lo_is_bad', 0),
                datetime.utcnow().isoformat(),
                uid
            )
        )
        conn.commit()
        row = conn.execute(
            'SELECT wp.*, u.name as updated_by_name FROM water_parameters wp LEFT JOIN users u ON u.id=wp.updated_by WHERE wp.parameter_name=?',
            (name,)
        ).fetchone()
        return jsonify(dict(row)), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': f'Parameter "{name}" already exists'}), 409
    finally:
        conn.close()

@app.route('/api/admin/parameters/<int:pid>', methods=['DELETE'])
@require_admin
def api_delete_parameter(pid):
    """Delete a water parameter (hard delete)."""
    conn = get_db()
    row = conn.execute('SELECT * FROM water_parameters WHERE id=?', (pid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Parameter not found'}), 404
    conn.execute('DELETE FROM water_parameters WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'deleted': row['parameter_name']})

# ─── ANALYZE ROUTE ────────────────────────────────────────────────────────────
@app.route('/analyze', methods=['POST'])
@require_auth
def analyze():
    try:
        data = request.get_json()
        if not data or 'file' not in data:
            return jsonify({'error': 'No file provided'}), 400

        file_b64 = data['file']
        file_type = data.get('type', 'image/jpeg')
        raw_bytes = base64.b64decode(file_b64)

        size_mb = len(raw_bytes) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            return jsonify({'error': f'File too large ({size_mb:.1f}MB). Maximum is {MAX_FILE_SIZE_MB}MB.'}), 400

        allowed_types = ['application/pdf', 'image/jpeg', 'image/png', 'image/jpg']
        if file_type not in allowed_types:
            return jsonify({'error': f'Unsupported file type: {file_type}'}), 400

        params = {}
        sample_info = ""
        lab_info = ""
        method_used = ""

        if file_type == 'application/pdf':
            params, sample_info, lab_info = extract_with_pdfplumber(raw_bytes)
            method_used = 'pdfplumber'
            if not params:
                import fitz
                doc = fitz.open(stream=raw_bytes, filetype='pdf')
                page = doc[0]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_bytes = pix.tobytes('jpeg')
                params, sample_info, lab_info = extract_with_easyocr(img_bytes)
                method_used = 'easyocr_fallback'
        else:
            params, sample_info, lab_info = extract_with_easyocr(raw_bytes)
            method_used = 'easyocr'

        confidence = 'high' if len(params) >= 5 else 'medium' if len(params) >= 2 else 'low'

        # ← Uses DB limits now
        safety_status = compute_safety_status(params)

        uid = request.current_user['sub']
        conn = get_db()
        conn.execute(
            '''INSERT INTO analyses (user_id, lab_info, sample_info, params, safety_status, method_used, confidence)
               VALUES (?,?,?,?,?,?,?)''',
            (uid, lab_info, sample_info, json.dumps(params), safety_status, method_used, confidence)
        )
        conn.commit()
        conn.close()

        return jsonify({
            'params': params,
            'sampleInfo': sample_info,
            'labInfo': lab_info,
            'confidence': confidence,
            'safetyStatus': safety_status,
            'notes': f'Extracted {len(params)} parameters using {method_used}',
            'method': method_used
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ─── HTML PAGES ───────────────────────────────────────────────────────────────
def serve_html(filename):
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return Response(f.read(), mimetype='text/html')
    return f'{filename} not found', 404

@app.route('/')
def index():
    return serve_html('login.html')

@app.route('/register')
def register_page():
    return serve_html('register.html')

@app.route('/app')
def app_page():
    return serve_html('chemsbury.html')

@app.route('/dashboard')
def dashboard_page():
    return serve_html('dashboard.html')

@app.route('/admin')
def admin_page():
    return serve_html('admin.html')

if __name__ == '__main__':
    logger.info(f"Starting Chemsbury on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
