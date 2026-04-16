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
        data = request.get_json(silent=True) or {}

        if 'file' not in data:
            return jsonify({'error': 'No file provided'}), 400

        raw_bytes = base64.b64decode(data['file'])
        claimed_type = data.get('type', 'image/jpeg')

        # size check
        size_mb = len(raw_bytes) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            return jsonify({'error': 'File too large'}), 400

        if claimed_type not in ALLOWED_MIME_TYPES:
            return jsonify({'error': 'Unsupported file type'}), 400

        ok, err = validate_upload(raw_bytes, claimed_type)
        if not ok:
            return jsonify({'error': err}), 400

        result = extract_params(raw_bytes, claimed_type)

        params = {
            k: float(v)
            for k, v in (result['params'] or {}).items()
            if v is not None and not isinstance(v, bool)
        }

        safety_status = compute_safety_status(params)

        uid = request.current_user['sub']

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

        return jsonify({
            'params': params,
            'paramUnits': result.get('extracted_units', {}),
            'sampleInfo': result['sample_info'],
            'labInfo': result['lab_info'],
            'rawText': result.get('raw_text', ''),
            'normalizedText': result.get('normalized_text', ''),
            'confidence': result['confidence'],
            'safetyStatus': safety_status,
            'notes': result['notes'],
            'method': result['method_used'],
        })

    except Exception as exc:
        logger.error(f"Analysis error: {exc}", exc_info=True)
        return jsonify({'error': str(exc)}), 500


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
    uid = request.current_user['sub']
    role = request.current_user.get('role')

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT * FROM analyses WHERE id=%s',
        (aid,)
    )

    rows = cursor.fetchall()
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

@analysis_bp.route('/api/parameters/public', methods=['GET'])
def public_parameters():
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
    return jsonify(data)
