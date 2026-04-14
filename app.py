"""
Chemsbury — Water Quality Analysis Platform
Flask application factory
"""
import os
import logging

from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(name)s — %(message)s',
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__, static_folder='static')

    # ── Config ────────────────────────────────────────────────────────────────
    from backend.config import ALLOWED_ORIGINS, PORT  # noqa — validates env at import

    CORS(app, origins=ALLOWED_ORIGINS)

    # ── Database ──────────────────────────────────────────────────────────────
    from backend.database import init_db
    init_db()

    # ── Blueprints ────────────────────────────────────────────────────────────
    from backend.routes.auth_routes     import auth_bp
    from backend.routes.analysis_routes import analysis_bp
    from backend.routes.admin_routes    import admin_bp
    from backend.routes.page_routes     import pages_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(pages_bp)

    # ── Health check (Railway uses this) ──────────────────────────────────────
    @app.route('/health')
    def health():
        return jsonify({'status': 'ok'}), 200
    
    @app.route('/')
def home():
    return "Chemsbury backend is running", 200

    # ── Security headers ──────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options']         = 'DENY'
        response.headers['Referrer-Policy']         = 'strict-origin-when-cross-origin'
        response.headers['X-XSS-Protection']        = '1; mode=block'
        return response

    logger.info("Chemsbury app created successfully")
    return app


app = create_app()

if __name__ == '__main__':
    from backend.config import PORT
    logger.info(f"Starting on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)