import os
from flask import Blueprint, Response
from flask import render_template
from backend.database import get_db
from flask import Blueprint, Response
import os

pages_bp = Blueprint('pages', __name__)

@pages_bp.route('/debug-users')
def debug_users():
    db = get_db()
    users = db.execute("SELECT * FROM users").fetchall()
    return [dict(u) for u in users]


_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _serve(filename: str):
    path = os.path.join(_BASE, 'templates', filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return Response(f.read(), mimetype='text/html')
    return f'{filename} not found', 404


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
