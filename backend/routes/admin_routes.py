from datetime import datetime
from flask import Blueprint, request, jsonify

from backend.auth import require_admin
from backend.database import get_db, rows_to_dicts

admin_bp = Blueprint('admin', __name__)


# ── USERS ─────────────────────────────────────────

@admin_bp.route('/api/admin/users', methods=['GET'])
@require_admin
def list_users():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT u.id, u.name, u.email, u.company, u.role, u.created_at,
               COUNT(a.id) AS analysis_count
        FROM users u
        LEFT JOIN analyses a ON a.user_id = u.id
        GROUP BY u.id
        ORDER BY u.created_at DESC
    ''')

    rows = cursor.fetchall()
    users = rows_to_dicts(cursor, rows)

    conn.close()
    return jsonify(users)


# ── ANALYSES ─────────────────────────────────────

@admin_bp.route('/api/admin/analyses', methods=['GET'])
@require_admin
def list_all_analyses():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT a.id, a.user_id, a.lab_info, a.sample_info, a.safety_status,
               a.method_used, a.confidence, a.created_at,
               u.name AS user_name, u.email AS user_email
        FROM analyses a
        JOIN users u ON u.id = a.user_id
        ORDER BY a.created_at DESC
        LIMIT 200
    ''')

    rows = cursor.fetchall()
    data = rows_to_dicts(cursor, rows)

    conn.close()
    return jsonify(data)


# ── ROLE UPDATE ───────────────────────────────────

@admin_bp.route('/api/admin/users/<int:uid>/role', methods=['PUT'])
@require_admin
def set_role(uid):
    data = request.get_json(silent=True) or {}
    role = data.get('role')

    if role not in ('user', 'admin'):
        return jsonify({'error': 'Invalid role'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        'UPDATE users SET role=%s WHERE id=%s',
        (role, uid)
    )

    conn.commit()
    conn.close()

    return jsonify({'ok': True})


# ── DELETE USER ───────────────────────────────────

@admin_bp.route('/api/admin/users/<int:uid>', methods=['DELETE'])
@require_admin
def delete_user(uid):
    me_id = request.current_user['sub']

    if uid == me_id:
        return jsonify({'error': 'Cannot delete your own account'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM analyses WHERE user_id=%s', (uid,))
    cursor.execute('DELETE FROM users WHERE id=%s', (uid,))

    conn.commit()
    conn.close()

    return jsonify({'ok': True})


# ── PARAMETERS ───────────────────────────────────

@admin_bp.route('/api/admin/parameters', methods=['GET'])
@require_admin
def get_parameters():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT wp.*, u.name AS updated_by_name
        FROM water_parameters wp
        LEFT JOIN users u ON u.id = wp.updated_by
        ORDER BY wp.parameter_name ASC
    ''')

    rows = cursor.fetchall()
    data = rows_to_dicts(cursor, rows)

    conn.close()
    return jsonify(data)


@admin_bp.route('/api/admin/parameters/<int:pid>', methods=['PUT'])
@require_admin
def update_parameter(pid):
    data = request.get_json(silent=True) or {}

    allowed = {
        'unit', 'permissible_limit', 'acceptable_limit',
        'hi_is_bad', 'lo_limit', 'lo_is_bad', 'is_active',
    }

    updates = {k: v for k, v in data.items() if k in allowed}

    if not updates:
        return jsonify({'error': 'No valid fields'}), 400

    updates['updated_at'] = datetime.utcnow().isoformat()
    updates['updated_by'] = request.current_user['sub']

    set_clause = ', '.join(f"{k}=%s" for k in updates)
    values = list(updates.values()) + [pid]

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        f'UPDATE water_parameters SET {set_clause} WHERE id=%s',
        values
    )

    conn.commit()

    cursor.execute('''
        SELECT wp.*, u.name AS updated_by_name
        FROM water_parameters wp
        LEFT JOIN users u ON u.id = wp.updated_by
        WHERE wp.id=%s
    ''', (pid,))

    row = cursor.fetchall()
    result = rows_to_dicts(cursor, row)

    conn.close()

    return jsonify(result[0] if result else {})


@admin_bp.route('/api/admin/parameters', methods=['POST'])
@require_admin
def add_parameter():
    data = request.get_json(silent=True) or {}
    name = (data.get('parameter_name') or '').strip().lower()

    if not name:
        return jsonify({'error': 'parameter_name required'}), 400

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO water_parameters
            (parameter_name, unit, permissible_limit, acceptable_limit,
             hi_is_bad, lo_limit, lo_is_bad, updated_at, updated_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ''', (
            name,
            data.get('unit', ''),
            data.get('permissible_limit'),
            data.get('acceptable_limit'),
            data.get('hi_is_bad', 1),
            data.get('lo_limit'),
            data.get('lo_is_bad', 0),
            datetime.utcnow().isoformat(),
            request.current_user['sub'],
        ))

        conn.commit()

        return jsonify({'ok': True}), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 400

    finally:
        conn.close()


@admin_bp.route('/api/admin/parameters/<int:pid>', methods=['DELETE'])
@require_admin
def delete_parameter(pid):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT parameter_name FROM water_parameters WHERE id=%s',
        (pid,)
    )

    row = cursor.fetchone()

    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    cursor.execute(
        'DELETE FROM water_parameters WHERE id=%s',
        (pid,)
    )

    conn.commit()
    conn.close()

    return jsonify({'ok': True})