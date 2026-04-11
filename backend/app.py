"""
Chemsbury Water Analysis Platform
Flask application factory.
"""
import logging
from flask import Flask, jsonify
from flask_cors import CORS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    from backend.config import ALLOWED_ORIGINS, PORT
    from backend.database import init_db
    from backend.routes import auth_bp, analysis_bp, admin_bp, pages_bp

    app = Flask(__name__, static_folder='static', static_url_path='/static')
    app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024  # 12 MB hard limit

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS(app, origins=ALLOWED_ORIGINS)

    # ── Security headers ──────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options']         = 'DENY'
        response.headers['Referrer-Policy']         = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data:;"
        )
        return response

    # ── Blueprints ────────────────────────────────────────────────────────────
    for bp in (auth_bp, analysis_bp, admin_bp, pages_bp):
        app.register_blueprint(bp)

    # ── Global error handlers ─────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(_):
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(413)
    def too_large(_):
        return jsonify({'error': 'File too large. Maximum upload size is 10 MB.'}), 413

    @app.errorhandler(500)
    def server_error(exc):
        logger.error(f"Unhandled exception: {exc}")
        return jsonify({'error': 'Internal server error'}), 500

    # ── DB init ───────────────────────────────────────────────────────────────
    init_db()

    logger.info("Chemsbury app created successfully.")
    return app


app = create_app()

if __name__ == '__main__':
    from backend.config import PORT
    logger.info(f"Starting on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
