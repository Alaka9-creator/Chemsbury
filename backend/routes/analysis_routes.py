import base64
import json
import logging

from flask import Blueprint, request, jsonify
auth_bp = Blueprint('auth', __name__)
from backend.auth import require_auth
from backend.database import get_db
from backend.ocr import extract_params, validate_upload
from backend.safety import compute_safety_status
from backend.config import MAX_FILE_SIZE_MB, ALLOWED_MIME_TYPES
from backend.database import get_db

@auth_bp.route('/debug-users')
def debug_users():
    db = get_db()
    users = db.execute("SELECT * FROM users").fetchall()
    return [dict(u) for u in users]
logger = logging.getLogger(__name__)

analysis_bp = Blueprint('analysis', __name__)


@analysis_bp.route('/analyze', methods=['POST'])
@require_auth
def analyze():
    try:
        data = request.get_json(silent=True) or {}
        if 'file' not in data:
            return jsonify({'error': 'No file provided'}), 400

        raw_bytes   = base64.b64decode(data['file'])
        claimed_type = data.get('type', 'image/jpeg')

        # ── Size check ────────────────────────────────────────────────────────
        size_mb = len(raw_bytes) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            return jsonify({
                'error': f'File too large ({size_mb:.1f} MB). Maximum is {MAX_FILE_SIZE_MB} MB.'
            }), 400

        # ── Claimed type check ────────────────────────────────────────────────
        if claimed_type not in ALLOWED_MIME_TYPES:
            return jsonify({'error': f'Unsupported file type: {claimed_type}'}), 400

        # ── Magic-byte validation (server-side, not trusting client) ──────────
        ok, err = validate_upload(raw_bytes, claimed_type)
        if not ok:
            return jsonify({'error': err}), 400

        # ── Extract ───────────────────────────────────────────────────────────
        result      = extract_params(raw_bytes, claimed_type)
        params      = {
            k: float(v)
            for k, v in (result['params'] or {}).items()
            if v is not None and not isinstance(v, bool)
        }
        safety_status = compute_safety_status(params)

        # ── Persist ───────────────────────────────────────────────────────────
        uid  = request.current_user['sub']
        conn = get_db()
        conn.execute(
            'INSERT INTO analyses '
            '(user_id, lab_info, sample_info, params, safety_status, method_used, confidence) '
            'VALUES (?,?,?,?,?,?,?)',
            (
                uid,
                result['lab_info'],
                result['sample_info'],
                json.dumps(params),
                safety_status,
                result['method_used'],
                result['confidence'],
            ),
        )
        conn.commit()
        conn.close()

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
        import traceback
        traceback.print_exc()
        logger.error(f"Analysis error: {exc}")
        return jsonify({'error': str(exc)}), 500


@analysis_bp.route('/api/analyses', methods=['GET'])
@require_auth
def list_analyses():
    uid  = request.current_user['sub']
    conn = get_db()
    rows = conn.execute(
        'SELECT id, lab_info, sample_info, safety_status, method_used, '
        'confidence, created_at '
        'FROM analyses WHERE user_id=? ORDER BY created_at DESC',
        (uid,),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@analysis_bp.route('/api/analyses/<int:aid>', methods=['GET'])
@require_auth
def get_analysis(aid):
    uid  = request.current_user['sub']
    role = request.current_user.get('role')
    conn = get_db()
    row  = conn.execute('SELECT * FROM analyses WHERE id=?', (aid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    if row['user_id'] != uid and role != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    d = dict(row)
    if d.get('params'):
        d['params'] = json.loads(d['params'])
    return jsonify(d)


# ── Public parameter definitions (for frontend dynamic loading) ───────────────
@analysis_bp.route('/api/parameters/public', methods=['GET'])
def public_parameters():
    """Return active parameters — no auth required (limits are public info)."""
    conn = get_db()
    rows = conn.execute(
        'SELECT parameter_name, unit, permissible_limit, acceptable_limit, '
        'hi_is_bad, lo_limit, lo_is_bad '
        'FROM water_parameters WHERE is_active=1 ORDER BY parameter_name'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])
