from datetime import datetime
import sqlite3

from flask import Blueprint, request, jsonify

from backend.auth import require_admin, require_auth
from backend.database import get_db

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/api/admin/users', methods=['GET'])
@require_admin
def list_users():
    conn  = get_db()
    users = conn.execute(
        '''SELECT u.id, u.name, u.email, u.company, u.role, u.created_at,
                  COUNT(a.id) AS analysis_count
           FROM users u
           LEFT JOIN analyses a ON a.user_id = u.id
           GROUP BY u.id
           ORDER BY u.created_at DESC'''
    ).fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])


@admin_bp.route('/api/admin/analyses', methods=['GET'])
@require_admin
def list_all_analyses():
    conn = get_db()
    rows = conn.execute(
        '''SELECT a.id, a.user_id, a.lab_info, a.sample_info, a.safety_status,
                  a.method_used, a.confidence, a.created_at,
                  u.name AS user_name, u.email AS user_email
           FROM analyses a
           JOIN users u ON u.id = a.user_id
           ORDER BY a.created_at DESC
           LIMIT 200'''
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.route('/api/admin/users/<int:uid>/role', methods=['PUT'])
@require_admin
def set_role(uid):
    data = request.get_json(silent=True) or {}
    role = data.get('role')
    if role not in ('user', 'admin'):
        return jsonify({'error': 'Invalid role'}), 400
    conn = get_db()
    conn.execute('UPDATE users SET role=? WHERE id=?', (role, uid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@admin_bp.route('/api/admin/users/<int:uid>', methods=['DELETE'])
@require_admin
def delete_user(uid):
    me_id = request.current_user['sub']
    if uid == me_id:
        return jsonify({'error': 'Cannot delete your own account'}), 400
    conn = get_db()
    conn.execute('DELETE FROM analyses WHERE user_id=?', (uid,))
    conn.execute('DELETE FROM users WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ── Water Parameters ──────────────────────────────────────────────────────────

@admin_bp.route('/api/admin/parameters', methods=['GET'])
@require_admin
def get_parameters():
    conn = get_db()
    rows = conn.execute(
        '''SELECT wp.*, u.name AS updated_by_name
           FROM water_parameters wp
           LEFT JOIN users u ON u.id = wp.updated_by
           ORDER BY wp.parameter_name ASC'''
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.route('/api/admin/parameters/<int:pid>', methods=['PUT'])
@require_admin
def update_parameter(pid):
    data    = request.get_json(silent=True) or {}
    allowed = {
        'unit', 'permissible_limit', 'acceptable_limit',
        'hi_is_bad', 'lo_limit', 'lo_is_bad', 'is_active',
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'No valid fields to update'}), 400

    uid = request.current_user['sub']
    updates['updated_at'] = datetime.utcnow().isoformat()
    updates['updated_by'] = uid

    set_clause = ', '.join(f"{k}=?" for k in updates)
    values     = list(updates.values()) + [pid]

    conn = get_db()
    conn.execute(f'UPDATE water_parameters SET {set_clause} WHERE id=?', values)
    conn.commit()
    row = conn.execute(
        'SELECT wp.*, u.name AS updated_by_name '
        'FROM water_parameters wp '
        'LEFT JOIN users u ON u.id = wp.updated_by '
        'WHERE wp.id=?',
        (pid,),
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Parameter not found'}), 404
    return jsonify(dict(row))


@admin_bp.route('/api/admin/parameters', methods=['POST'])
@require_admin
def add_parameter():
    data = request.get_json(silent=True) or {}
    name = (data.get('parameter_name') or '').strip().lower()[:100]
    if not name:
        return jsonify({'error': 'parameter_name is required'}), 400

    uid  = request.current_user['sub']
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
                uid,
            ),
        )
        conn.commit()
        row = conn.execute(
            'SELECT wp.*, u.name AS updated_by_name '
            'FROM water_parameters wp '
            'LEFT JOIN users u ON u.id = wp.updated_by '
            'WHERE wp.parameter_name=?',
            (name,),
        ).fetchone()
        return jsonify(dict(row)), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': f'Parameter "{name}" already exists'}), 409
    finally:
        conn.close()


@admin_bp.route('/api/admin/parameters/<int:pid>', methods=['DELETE'])
@require_admin
def delete_parameter(pid):
    conn = get_db()
    row  = conn.execute(
        'SELECT * FROM water_parameters WHERE id=?', (pid,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Parameter not found'}), 404
    conn.execute('DELETE FROM water_parameters WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'deleted': row['parameter_name']})
