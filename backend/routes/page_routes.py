import os
from flask import Blueprint, Response

pages_bp = Blueprint('pages', __name__)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _serve(filename: str):
    path = os.path.join(_BASE, filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return Response(f.read(), mimetype='text/html')
    return f'{filename} not found', 404


@pages_bp.route('/')
def index():
    return _serve('login.html')


@pages_bp.route('/register')
def register_page():
    return _serve('register.html')


@pages_bp.route('/app')
def app_page():
    return _serve('chemsbury.html')


@pages_bp.route('/dashboard')
def dashboard_page():
    return _serve('dashboard.html')


@pages_bp.route('/admin')
def admin_page():
    return _serve('admin.html')
