import base64
import json
import logging

from flask import Blueprint, request, jsonify
from backend.auth import require_auth
from backend.database import get_db, rows_to_dicts
from backend.ocr import extract_params, validate_upload
from backend.safety import compute_safety_status
from backend.config import MAX_FILE_SIZE_MB, ALLOWED_MIME_TYPES

analysis_bp = Blueprint('analysis', __name__)

logger = logging.getLogger(__name__)


# ── ANALYZE ─────────────────────────────────────

@analysis_bp.route('/analyze', methods=['POST'])
@require_auth
def analyze():
    try:
        raw_bytes = None
        claimed_type = 'application/pdf'

        # ── Accept multipart/form-data (standard file upload) ────────────────
        if request.files and 'file' in request.files:
            f = request.files['file']
            raw_bytes = f.read()
            claimed_type = f.content_type or 'application/pdf'
            logger.info(f"Received multipart upload: {f.filename!r}, type={claimed_type}, size={len(raw_bytes)}")

        # ── Accept application/json with base64-encoded file ─────────────────
        elif request.is_json or request.content_type == 'application/json':
            data = request.get_json(silent=True) or {}
            if 'file' not in data:
                return jsonify({'error': 'No file provided. Send multipart/form-data with a "file" field, or JSON with a base64-encoded "file" field.'}), 400
            try:
                raw_bytes = base64.b64decode(data['file'])
            except Exception as decode_err:
                return jsonify({'error': f'Invalid base64 encoding: {decode_err}'}), 400
            claimed_type = data.get('type', 'application/pdf')
            logger.info(f"Received JSON/base64 upload: type={claimed_type}, size={len(raw_bytes)}")

        else:
            return jsonify({'error': 'No file received. Use multipart/form-data with field name "file".'}), 400

        if not raw_bytes:
            return jsonify({'error': 'Uploaded file is empty.'}), 400

        # ── Normalise MIME type ───────────────────────────────────────────────
        # Browsers sometimes send 'image/jpg'; normalise to 'image/jpeg'
        if claimed_type == 'image/jpg':
            claimed_type = 'image/jpeg'

        # ── Size check ────────────────────────────────────────────────────────
        size_mb = len(raw_bytes) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            return jsonify({'error': f'File too large ({size_mb:.1f} MB). Maximum is {MAX_FILE_SIZE_MB} MB.'}), 400

        if claimed_type not in ALLOWED_MIME_TYPES:
            return jsonify({'error': f'Unsupported file type: {claimed_type}. Allowed: {", ".join(ALLOWED_MIME_TYPES)}'}), 400

        # ── Magic-byte validation ─────────────────────────────────────────────
        ok, err = validate_upload(raw_bytes, claimed_type)
        if not ok:
            return jsonify({'error': err}), 400

        # ── OCR / extraction ──────────────────────────────────────────────────
        logger.info(f"Starting extraction: mime={claimed_type}")
        result = extract_params(raw_bytes, claimed_type)
        logger.info(f"Extraction done: method={result.get('method_used')}, confidence={result.get('confidence')}, params_found={len(result.get('params', {}))}")

        params = {
            k: float(v)
            for k, v in (result['params'] or {}).items()
            if v is not None and not isinstance(v, bool)
        }

        safety_status = compute_safety_status(params)

        # ── Persist to DB ─────────────────────────────────────────────────────
        uid = request.current_user['sub']
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO analyses
                   (user_id, lab_info, sample_info, params, safety_status, method_used, confidence)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                (
                    uid,
                    result['lab_info'],
                    result['sample_info'],
                    json.dumps(params),
                    safety_status,
                    result['method_used'],
                    result['confidence'],
                )
            )
            conn.commit()
            conn.close()
        except Exception as db_err:
            # Don't fail the whole request just because DB insert failed
            logger.error(f"DB insert failed (returning result anyway): {db_err}", exc_info=True)

        return jsonify({
            'params':       params,
            'sampleInfo':   result['sample_info'],
            'labInfo':      result['lab_info'],
            'confidence':   result['confidence'],
            'safetyStatus': safety_status,
            'notes':        result['notes'],
            'method':       result['method_used'],
        })

    except Exception as exc:
        logger.error(f"Unhandled error in /analyze: {exc}", exc_info=True)
        return jsonify({'error': f'Analysis failed: {str(exc)}'}), 500


# ── LIST ANALYSES ───────────────────────────────

@analysis_bp.route('/api/analyses', methods=['GET'])
@require_auth
def list_analyses():
    uid = request.current_user['sub']
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''SELECT id, lab_info, sample_info, safety_status,
                  method_used, confidence, created_at
           FROM analyses
           WHERE user_id=%s
           ORDER BY created_at DESC''',
        (uid,)
    )
    rows = cursor.fetchall()
    data = rows_to_dicts(cursor, rows)
    conn.close()
    return jsonify(data)


# ── GET SINGLE ANALYSIS ─────────────────────────

@analysis_bp.route('/api/analyses/<int:aid>', methods=['GET'])
@require_auth
def get_analysis(aid):
    uid  = request.current_user['sub']
    role = request.current_user.get('role')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM analyses WHERE id=%s', (aid,))
    rows   = cursor.fetchall()
    result = rows_to_dicts(cursor, rows)
    conn.close()

    if not result:
        return jsonify({'error': 'Not found'}), 404

    d = result[0]
    if d['user_id'] != uid and role != 'admin':
        return jsonify({'error': 'Forbidden'}), 403

    if d.get('params'):
        d['params'] = json.loads(d['params'])

    return jsonify(d)


# ── PUBLIC PARAMETERS ───────────────────────────
# Two URL aliases so both /api/params and /api/parameters/public work.

_BIS_DEFAULTS = [
    {'parameter_name': 'ph',          'unit': '',       'permissible_limit': 8.5,   'acceptable_limit': 6.5,   'hi_is_bad': True,  'lo_limit': 6.5,  'lo_is_bad': True},
    {'parameter_name': 'turbidity',   'unit': 'NTU',    'permissible_limit': 5.0,   'acceptable_limit': 1.0,   'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'tds',         'unit': 'mg/L',   'permissible_limit': 500.0, 'acceptable_limit': 500.0, 'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'hardness',    'unit': 'mg/L',   'permissible_limit': 300.0, 'acceptable_limit': 200.0, 'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'iron',        'unit': 'mg/L',   'permissible_limit': 0.3,   'acceptable_limit': 0.1,   'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'chloride',    'unit': 'mg/L',   'permissible_limit': 250.0, 'acceptable_limit': 250.0, 'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'fluoride',    'unit': 'mg/L',   'permissible_limit': 1.5,   'acceptable_limit': 1.0,   'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'nitrate',     'unit': 'mg/L',   'permissible_limit': 45.0,  'acceptable_limit': 45.0,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'nitrite',     'unit': 'mg/L',   'permissible_limit': 3.0,   'acceptable_limit': 3.0,   'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'manganese',   'unit': 'mg/L',   'permissible_limit': 0.1,   'acceptable_limit': 0.05,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'sulphate',    'unit': 'mg/L',   'permissible_limit': 200.0, 'acceptable_limit': 200.0, 'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'alkalinity',  'unit': 'mg/L',   'permissible_limit': 200.0, 'acceptable_limit': 200.0, 'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'calcium',     'unit': 'mg/L',   'permissible_limit': 75.0,  'acceptable_limit': 75.0,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'magnesium',   'unit': 'mg/L',   'permissible_limit': 30.0,  'acceptable_limit': 30.0,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'copper',      'unit': 'mg/L',   'permissible_limit': 0.05,  'acceptable_limit': 0.05,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'zinc',        'unit': 'mg/L',   'permissible_limit': 5.0,   'acceptable_limit': 5.0,   'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'arsenic',     'unit': 'mg/L',   'permissible_limit': 0.01,  'acceptable_limit': 0.01,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'lead',        'unit': 'mg/L',   'permissible_limit': 0.01,  'acceptable_limit': 0.01,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'chromium',    'unit': 'mg/L',   'permissible_limit': 0.05,  'acceptable_limit': 0.05,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'aluminium',   'unit': 'mg/L',   'permissible_limit': 0.03,  'acceptable_limit': 0.03,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'ammonia',     'unit': 'mg/L',   'permissible_limit': 0.5,   'acceptable_limit': 0.5,   'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'h2s',         'unit': 'mg/L',   'permissible_limit': 0.05,  'acceptable_limit': 0.05,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'coliform',    'unit': 'MPN/100mL', 'permissible_limit': 0, 'acceptable_limit': 0,     'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'ecoli',       'unit': 'MPN/100mL', 'permissible_limit': 0, 'acceptable_limit': 0,     'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'colour',      'unit': 'Hazen',  'permissible_limit': 15.0,  'acceptable_limit': 5.0,   'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'tss',         'unit': 'mg/L',   'permissible_limit': 10.0,  'acceptable_limit': 10.0,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'bod',         'unit': 'mg/L',   'permissible_limit': 3.0,   'acceptable_limit': 3.0,   'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'cod',         'unit': 'mg/L',   'permissible_limit': 10.0,  'acceptable_limit': 10.0,  'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'boron',       'unit': 'mg/L',   'permissible_limit': 0.5,   'acceptable_limit': 0.5,   'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
    {'parameter_name': 'phenol',      'unit': 'mg/L',   'permissible_limit': 0.001, 'acceptable_limit': 0.001, 'hi_is_bad': True,  'lo_limit': None, 'lo_is_bad': False},
]


def _get_public_parameters():
    """Try DB first; fall back to BIS hardcoded defaults if DB is empty or fails."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT parameter_name, unit, permissible_limit,
                      acceptable_limit, hi_is_bad, lo_limit, lo_is_bad
               FROM water_parameters
               WHERE is_active=TRUE
               ORDER BY parameter_name'''
        )
        rows = cursor.fetchall()
        data = rows_to_dicts(cursor, rows)
        conn.close()
        if data:
            return data
    except Exception as e:
        logger.warning(f"DB parameter fetch failed, using BIS defaults: {e}")

    return _BIS_DEFAULTS


@analysis_bp.route('/api/parameters/public', methods=['GET'])
def public_parameters():
    return jsonify(_get_public_parameters())


@analysis_bp.route('/api/params', methods=['GET'])
def public_params_alias():
    """Alias for /api/parameters/public — supports older frontend calls."""
    return jsonify(_get_public_parameters())
