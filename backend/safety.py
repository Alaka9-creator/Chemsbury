import logging
from backend.database import get_db

logger = logging.getLogger(__name__)

# Hardcoded fallback if DB is unavailable
_FALLBACK_LIMITS = {
    'ph':         {'permissible_limit': 8.5,  'acceptable_limit': 6.5,
                   'hi_is_bad': 1, 'lo_limit': 6.5, 'lo_is_bad': 1},
    'tds':        {'permissible_limit': 500,  'acceptable_limit': 500,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'iron':       {'permissible_limit': 0.3,  'acceptable_limit': 0.1,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'hardness':   {'permissible_limit': 300,  'acceptable_limit': 200,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'chloride':   {'permissible_limit': 250,  'acceptable_limit': 250,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'turbidity':  {'permissible_limit': 5,    'acceptable_limit': 1,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'h2s':        {'permissible_limit': 0.05, 'acceptable_limit': 0.05,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'nitrate':    {'permissible_limit': 45,   'acceptable_limit': 45,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'manganese':  {'permissible_limit': 0.1,  'acceptable_limit': 0.05,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'fluoride':   {'permissible_limit': 1.5,  'acceptable_limit': 1.0,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'alkalinity': {'permissible_limit': 200,  'acceptable_limit': 200,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'coliform':   {'permissible_limit': 0,    'acceptable_limit': 0,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'arsenic':    {'permissible_limit': 0.01, 'acceptable_limit': 0.01,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'lead':       {'permissible_limit': 0.01, 'acceptable_limit': 0.01,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
    'ecoli':      {'permissible_limit': 0,    'acceptable_limit': 0,
                   'hi_is_bad': 1, 'lo_limit': None, 'lo_is_bad': 0},
}


def get_limits_from_db() -> dict:
    """Return active parameter limits from DB, falling back to hardcoded."""
    try:
        conn = get_db()
        rows = conn.execute(
            'SELECT * FROM water_parameters WHERE is_active = 1'
        ).fetchall()
        conn.close()
        return {
            row['parameter_name']: {
                'permissible_limit': row['permissible_limit'],
                'acceptable_limit':  row['acceptable_limit'],
                'hi_is_bad':         row['hi_is_bad'],
                'lo_limit':          row['lo_limit'],
                'lo_is_bad':         row['lo_is_bad'],
            }
            for row in rows
        }
    except Exception as exc:
        logger.warning(f"DB limit load failed, using fallback: {exc}")
        return _FALLBACK_LIMITS


def compute_safety_status(params: dict) -> str:
    """
    Returns 'safe', 'caution', or 'unsafe'.

    Logic (fixes the original broken pH / range-param logic):
      - unsafe  → value > permissible_limit * 1.5
                  OR value < lo_limit * 0.5   (critically low)
                  OR value > 0 when permissible_limit == 0 (e.g. coliform/ecoli)
      - caution → value > permissible_limit
                  OR value < lo_limit (below safe floor)
      - safe    → all within limits
    """
    limits  = get_limits_from_db()
    overall = 'safe'

    for param_name, lim in limits.items():
        v = params.get(param_name)
        if v is None:
            continue

        perm   = lim.get('permissible_limit')
        lo     = lim.get('lo_limit')
        hi_bad = lim.get('hi_is_bad', 1)
        lo_bad = lim.get('lo_is_bad', 0)

        # ── High limit check ──────────────────────────────────────────────────
        if hi_bad and perm is not None:
            if perm == 0 and v > 0:
                # Zero-tolerance params (coliform, ecoli) → always unsafe
                return 'unsafe'
            if perm > 0:
                if v > perm * 1.5:
                    return 'unsafe'
                if v > perm and overall == 'safe':
                    overall = 'caution'

        # ── Low limit check ───────────────────────────────────────────────────
        if lo_bad and lo is not None:
            if lo > 0 and v < lo * 0.5:
                return 'unsafe'
            if v < lo and overall == 'safe':
                overall = 'caution'

    return overall
