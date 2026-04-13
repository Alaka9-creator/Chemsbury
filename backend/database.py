import sqlite3
import logging
from backend.config import DB_PATH

logger = logging.getLogger(__name__)

IS10500_DEFAULTS = [
    ('ph',          '',           8.5,   6.5,  1, 6.5,  1),
    ('turbidity',   'NTU',        5.0,   1.0,  1, None, 0),
    ('tds',         'mg/L',     500.0, 500.0,  1, None, 0),
    ('hardness',    'mg/L',     300.0, 200.0,  1, None, 0),
    ('iron',        'mg/L',       0.3,   0.1,  1, None, 0),
    ('chloride',    'mg/L',     250.0, 250.0,  1, None, 0),
    ('fluoride',    'mg/L',       1.5,   1.0,  1, None, 0),
    ('nitrate',     'mg/L',      45.0,  45.0,  1, None, 0),
    ('manganese',   'mg/L',       0.1,  0.05,  1, None, 0),
    ('alkalinity',  'mg/L',     200.0, 200.0,  1, None, 0),
    ('sulphate',    'mg/L',     200.0, 200.0,  1, None, 0),
    ('calcium',     'mg/L',      75.0,  75.0,  1, None, 0),
    ('magnesium',   'mg/L',      30.0,  30.0,  1, None, 0),
    ('copper',      'mg/L',      0.05,  0.05,  1, None, 0),
    ('zinc',        'mg/L',       5.0,   5.0,  1, None, 0),
    ('arsenic',     'mg/L',      0.01,  0.01,  1, None, 0),
    ('lead',        'mg/L',      0.01,  0.01,  1, None, 0),
    ('chromium',    'mg/L',      0.05,  0.05,  1, None, 0),
    ('aluminium',   'mg/L',       0.1,  0.03,  1, None, 0),
    ('ammonia',     'mg/L',       0.5,   0.5,  1, None, 0),
    ('h2s',         'mg/L',      0.05,  0.05,  1, None, 0),
    ('boron',       'mg/L',       1.0,   1.0,  1, None, 0),
    ('nitrite',     'mg/L',      0.02,  0.02,  1, None, 0),
    ('phenol',      'mg/L',     0.001, 0.001,  1, None, 0),
    ('coliform',    'MPN/100mL',  0.0,   0.0,  1, None, 0),
    ('ecoli',       'MPN/100mL',  0.0,   0.0,  1, None, 0),
    ('tss',         'mg/L',      10.0,  10.0,  1, None, 0),
    ('bod',         'mg/L',       2.0,   2.0,  1, None, 0),
    ('cod',         'mg/L',      10.0,  10.0,  1, None, 0),
    ('colour',      'Hazen',     15.0,   5.0,  1, None, 0),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            company       TEXT,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            role          TEXT    DEFAULT 'user',
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            lab_info      TEXT,
            sample_info   TEXT,
            params        TEXT,
            safety_status TEXT,
            method_used   TEXT,
            confidence    TEXT,
            notes         TEXT,
            created_at    TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS water_parameters (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            parameter_name    TEXT    NOT NULL UNIQUE,
            unit              TEXT,
            permissible_limit REAL,
            acceptable_limit  REAL,
            hi_is_bad         INTEGER DEFAULT 1,
            lo_limit          REAL,
            lo_is_bad         INTEGER DEFAULT 0,
            is_active         INTEGER DEFAULT 1,
            updated_at        TEXT,
            updated_by        INTEGER REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS password_resets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            token_hash TEXT    NOT NULL UNIQUE,
            expires_at TEXT    NOT NULL,
            used       INTEGER DEFAULT 0,
            created_at TEXT    DEFAULT (datetime('now'))
        );
    ''')
    conn.commit()

    count = conn.execute('SELECT COUNT(*) FROM water_parameters').fetchone()[0]
    if count == 0:
        conn.executemany(
            '''INSERT OR IGNORE INTO water_parameters
               (parameter_name, unit, permissible_limit, acceptable_limit,
                hi_is_bad, lo_limit, lo_is_bad)
               VALUES (?,?,?,?,?,?,?)''',
            IS10500_DEFAULTS
        )
        conn.commit()
        logger.info(f"Seeded {len(IS10500_DEFAULTS)} IS:10500 parameters.")

    conn.close()
    logger.info("Database initialised.")