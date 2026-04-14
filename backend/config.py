import os
import sys
print("CONFIG FILE VERSION: NEW")
print("SMTP_HOST exists?", "SMTP_HOST" in globals())
# ── JWT ───────────────────────────────────────────────────────────────────────
JWT_SECRET = os.environ.get('JWT_SECRET')
if not JWT_SECRET:
    print("FATAL: JWT_SECRET environment variable must be set.", file=sys.stderr)
    sys.exit(1)

# ── Domain ────────────────────────────────────────────────────────────────────
ALLOWED_DOMAIN = os.environ.get('ALLOWED_DOMAIN', 'chemsbury.in')

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get('DB_PATH', 'chemsbury.db')
_ALLOWED_DB_PREFIXES = ('/', './')
assert any(DB_PATH.startswith(p) for p in _ALLOWED_DB_PREFIXES), \
    f"Invalid DB_PATH: {DB_PATH}"

# ── File Upload ───────────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB   = int(os.environ.get('MAX_FILE_SIZE_MB', 10))
ALLOWED_MIME_TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/jpg']

# ── CORS ──────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*').split(',')

# ── Rate Limiting ─────────────────────────────────────────────────────────────
LOGIN_MAX_ATTEMPTS   = int(os.environ.get('LOGIN_MAX_ATTEMPTS', 5))
LOGIN_WINDOW_SECONDS = int(os.environ.get('LOGIN_WINDOW_SECONDS', 300))

# ── Port ──────────────────────────────────────────────────────────────────────
PORT = int(os.environ.get('PORT', 3000))


# SMTP (optional — app works without these, just logs emails to console)
SMTP_HOST     = os.environ.get('SMTP_HOST',     '')
SMTP_PORT     = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER     = os.environ.get('SMTP_USER',     '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM     = os.environ.get('SMTP_FROM',     '')

# ── Frontend URL (used in password reset emails) ──────────────────────────────
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')