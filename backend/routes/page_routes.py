import os
from flask import Blueprint, Response, render_template

from backend.database import get_db, rows_to_dicts

pages_bp = Blueprint('pages', __name__)


# ── DEBUG ROUTE (REMOVE LATER) ──────────────────
@pages_bp.route('/debug-users')
def debug_users():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, email, role FROM users")
    rows = cursor.fetchall()

    users = rows_to_dicts(cursor, rows)

    conn.close()
    return users


# ── TEMPLATE ROUTES ─────────────────────────────

@pages_bp.route('/')
def index():
    return render_template("login.html")


@pages_bp.route('/register')
def register_page():
    return render_template("register.html")


@pages_bp.route('/app')
def app_page():
    return render_template("chemsbury.html")


@pages_bp.route('/dashboard')
def dashboard_page():
    return render_template("dashboard.html")


@pages_bp.route('/admin')
def admin_page():
    return render_template("admin.html")

@pages_bp.route('/forgot-password')
def forgot_password_page():
    return render_template("forgot_password.html")