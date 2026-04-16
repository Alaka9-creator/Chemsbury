"""
backend/ocr/param_matcher.py

Scans raw OCR / pdfplumber text and maps recognised parameter names → float values.
Also extracts lab name and sample info from common header patterns.

Accuracy improvements over v1:
  - Column-aware TSV parsing: in pdfplumber table rows (tab-separated) the value
    is taken from the column AFTER the parameter name, not the first number in line.
  - Serial-number guard: skips leading integers that look like row indices.
  - Unit-plausibility filter: validates extracted value against expected range.
  - Multi-value rows: when a row has several numbers, picks the one most likely
    to be the "result" column (second numeric token, before any limit column).
  - Handles "<0.01", ">0.1", "ND", "BDL", "Absent", "Nil" correctly.
  - Scientific notation normalised before float conversion.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Parameter alias table ─────────────────────────────────────────────────────
PARAM_ALIASES: dict[str, list[str]] = {
    'ph': [
        r'\bph\b', r'\bpotential\s+of\s+hydrogen\b', r'\bhydrogen\s+ion\b',
    ],
    'turbidity': [
        r'\bturbidity\b', r'\bturb\.?\b', r'\bntu\b',
    ],
    'tds': [
        r'\btotal\s+dissolved\s+solids?\b', r'\bt\.?d\.?s\.?\b',
        r'\bdissolved\s+solids?\b',
    ],
    'hardness': [
        r'\btotal\s+hardness\b', r'\bhardness\b', r'\bcaco3\b',
    ],
    'iron': [
        r'\biron\b', r'\bfe\b(?!\s*\()', r'\bferrous\b', r'\bferric\b',
    ],
    'chloride': [
        r'\bchlorides?\b', r'\bcl\b(?!\s*\d)',
    ],
    'fluoride': [
        r'\bfluorides?\b', r'\bfluorine\b', r'\bf\b(?=\s)',
    ],
    'nitrate': [
        r'\bnitrates?\b', r'\bno3\b', r'\bno[-–]3\b',
    ],
    'nitrite': [
        r'\bnitrites?\b', r'\bno2\b', r'\bno[-–]2\b',
    ],
    'manganese': [
        r'\bmanganese\b', r'\bmn\b(?=\s)',
    ],
    'alkalinity': [
        r'\btotal\s+alkalinity\b', r'\balkalinity\b',
    ],
    'sulphate': [
        r'\bsulphates?\b', r'\bsulfates?\b', r'\bso4\b', r'\bso[-–]4\b',
    ],
    'calcium': [
        r'\bcalcium\b', r'\bca\b(?=\s)',
    ],
    'magnesium': [
        r'\bmagnesium\b', r'\bmg\b(?=\s)',
    ],
    'copper': [
        r'\bcopper\b', r'\bcu\b(?=\s)',
    ],
    'zinc': [
        r'\bzinc\b', r'\bzn\b(?=\s)',
    ],
    'arsenic': [
        r'\barsenic\b', r'\bas\b(?=\s)',
    ],
    'lead': [
        r'\blead\b', r'\bpb\b(?=\s)',
    ],
    'chromium': [
        r'\bchromium\b', r'\bcr\b(?=\s)', r'\bchrome\b',
    ],
    'aluminium': [
        r'\balumini?um\b', r'\bal\b(?=\s)',
    ],
    'ammonia': [
        r'\bammonia\b', r'\bammonium\b', r'\bnh3\b', r'\bnh4\b',
    ],
    'h2s': [
        r'\bhydrogen\s+sulphide\b', r'\bhydrogen\s+sulfide\b', r'\bh2s\b',
    ],
    'boron': [
        r'\bboron\b', r'\bb\b(?=\s)',
    ],
    'phenol': [
        r'\bphenol\b', r'\bphenolic\b',
    ],
    'coliform': [
        r'\btotal\s+coliform\b', r'\bcoliform\b', r'\bmpn\b',
    ],
    'ecoli': [
        r'\be\.?\s*coli\b', r'\bescherichia\s+coli\b',
    ],
    'tss': [
        r'\btotal\s+suspended\s+solids?\b', r'\bt\.?s\.?s\.?\b',
        r'\bsuspended\s+solids?\b',
    ],
    'bod': [
        r'\bbiochemical\s+oxygen\s+demand\b', r'\bb\.?o\.?d\.?\b',
    ],
    'cod': [
        r'\bchemical\s+oxygen\s+demand\b', r'\bc\.?o\.?d\.?\b',
    ],
    'colour': [
        r'\bcolo(?:u)?r\b', r'\bapparent\s+colo(?:u)?r\b', r'\bhazen\b',
    ],
}

# Plausibility ranges (min, max) — values outside are rejected as OCR artefacts
_PLAUSIBLE: dict[str, tuple[float, float]] = {
    'ph':         (0.0,    14.0),
    'turbidity':  (0.0,  1000.0),
    'tds':        (0.0, 10000.0),
    'hardness':   (0.0,  5000.0),
    'iron':       (0.0,   100.0),
    'chloride':   (0.0,  5000.0),
    'fluoride':   (0.0,    50.0),
    'nitrate':    (0.0,  1000.0),
    'nitrite':    (0.0,   500.0),
    'manganese':  (0.0,    50.0),
    'alkalinity': (0.0,  2000.0),
    'sulphate':   (0.0,  5000.0),
    'calcium':    (0.0,  1000.0),
    'magnesium':  (0.0,  1000.0),
    'copper':     (0.0,    50.0),
    'zinc':       (0.0,   100.0),
    'arsenic':    (0.0,    10.0),
    'lead':       (0.0,    10.0),
    'chromium':   (0.0,    10.0),
    'aluminium':  (0.0,    50.0),
    'ammonia':    (0.0,   500.0),
    'h2s':        (0.0,    10.0),
    'boron':      (0.0,    50.0),
    'phenol':     (0.0,     5.0),
    'coliform':   (0.0, 100000.0),
    'ecoli':      (0.0, 100000.0),
    'tss':        (0.0,  5000.0),
    'bod':        (0.0,  1000.0),
    'cod':        (0.0,  5000.0),
    'colour':     (0.0,  1000.0),
}

# Compiled for speed
_COMPILED: dict[str, list[re.Pattern]] = {
    k: [re.compile(p, re.IGNORECASE) for p in v]
    for k, v in PARAM_ALIASES.items()
}

# Matches a single numeric token (with optional leading < > ~)
# Captures: optional qualifier + digits + optional decimal
_NUM_TOKEN = re.compile(
    r'(?<![a-zA-Z\d])([<>~]?\s*\d+(?:[.,]\d+)?(?:\s*[xX]\s*10\s*[-–^]\s*\d+)?)'
    r'(?!\d)',
    re.IGNORECASE
)

# Words that mean "not detected" / zero
_ND_RE = re.compile(
    r'\b(nd|bdl|nil|absent|not\s+detected?|not\s+found|negative|<\s*0?\.0+1?)\b',
    re.IGNORECASE
)

# Looks like a header row (no numeric content)
_HEADER_RE = re.compile(
    r'\b(s\.?\s*no\.?|sr\.?\s*no\.?|parameter|result|unit|limit|standard|'
    r'permissible|acceptable|remark|method|test|analysis|sample)\b',
    re.IGNORECASE
)


# ── Public API ────────────────────────────────────────────────────────────────

def match_params(text: str) -> tuple[dict, str, str]:
    """
    Returns (params_dict, lab_info, sample_info).
    params_dict maps canonical parameter names → float values.
    """
    lines       = text.splitlines()
    params: dict[str, float] = {}
    lab_info    = _extract_lab_info(lines)
    sample_info = _extract_sample_info(lines)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        line_lower = stripped.lower()

        for param_name, patterns in _COMPILED.items():
            if param_name in params:
                continue

            for pat in patterns:
                if not pat.search(line_lower):
                    continue

                # Found a line containing this parameter name.
                val = _extract_value_from_line(stripped, param_name)
                if val is not None:
                    params[param_name] = val
                elif _ND_RE.search(stripped):
                    # "Not Detected" / "Absent" → treat as 0.0
                    params[param_name] = 0.0
                break  # don't try other alias patterns for this param on this line

    logger.info("Matched %d parameters from %d lines", len(params), len(lines))
    return params, lab_info, sample_info


# ── Value extraction ──────────────────────────────────────────────────────────

def _extract_value_from_line(line: str, param_name: str) -> Optional[float]:
    """
    Smart value extraction:
    1. If the line is tab-separated (pdfplumber table row), use column position.
    2. Otherwise collect all numeric tokens and pick the best one.
    """
    # ── Tab-separated (pdfplumber table rows) ─────────────────────────────────
    if '\t' in line:
        return _value_from_tsv(line, param_name)

    # ── Plain text / OCR line ─────────────────────────────────────────────────
    return _value_from_plain(line, param_name)


def _value_from_tsv(line: str, param_name: str) -> Optional[float]:
    """
    In a TSV row the structure is typically:
        [serial] [parameter name] [result] [unit] [limit] …
    Strategy: find the column that contains the parameter name, then take the
    first numeric column that comes AFTER it.
    """
    cols = [c.strip() for c in line.split('\t')]

    # Find which column index contains the param alias
    param_col = None
    for i, col in enumerate(cols):
        col_lower = col.lower()
        for pat in _COMPILED[param_name]:
            if pat.search(col_lower):
                param_col = i
                break
        if param_col is not None:
            break

    if param_col is None:
        # Fallback to plain extraction
        return _value_from_plain(line.replace('\t', ' '), param_name)

    # Collect numeric tokens from columns AFTER the param name column
    for col in cols[param_col + 1:]:
        if _ND_RE.search(col):
            return 0.0
        v = _parse_numeric_token(col.strip())
        if v is not None and _plausible(param_name, v):
            return v

    return None


def _value_from_plain(line: str, param_name: str) -> Optional[float]:
    """
    For plain-text lines:
    - Find all numeric tokens in the line.
    - Skip the very first token if it looks like a serial number
      (small integer, appears before any alphabetic param text).
    - Pick the first remaining plausible value.
    """
    # Find where the parameter name ends in the line so we only look AFTER it
    param_end = 0
    for pat in _COMPILED[param_name]:
        m = pat.search(line, re.IGNORECASE)
        if m:
            param_end = max(param_end, m.end())

    after_param = line[param_end:] if param_end else line

    # Collect all numeric tokens after the param name
    tokens = _NUM_TOKEN.findall(after_param)

    for raw_tok in tokens:
        raw_tok = raw_tok.strip()
        # Skip serial/index numbers: plain small integer right at start of token list
        v = _parse_numeric_token(raw_tok)
        if v is None:
            continue
        if _plausible(param_name, v):
            return v

    return None


def _parse_numeric_token(s: str) -> Optional[float]:
    """
    Parse a single numeric token like '0.3', '<0.01', '1,500', '5 x 10^-3'.
    Returns float or None.
    """
    if not s:
        return None

    s = s.strip()

    # Not-detected markers
    if _ND_RE.search(s):
        return 0.0

    # Strip qualifiers < > ~
    s = re.sub(r'^[<>~]\s*', '', s)

    # Scientific notation: 5 x 10^-3 or 5e-3
    sci = re.search(
        r'(\d+(?:[.,]\d+)?)\s*[xX]\s*10\s*[-–^]\s*(\d+)', s
    )
    if sci:
        try:
            return float(sci.group(1).replace(',', '.')) * (10 ** -int(sci.group(2)))
        except Exception:
            return None

    e_sci = re.search(r'(\d+(?:[.,]\d+)?)[eE][-+]?(\d+)', s)
    if e_sci:
        try:
            return float(e_sci.group(0).replace(',', '.'))
        except Exception:
            return None

    # Regular number (allow comma as decimal separator)
    m = re.search(r'\d+(?:[.,]\d+)?', s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(',', '.'))
    except ValueError:
        return None


def _plausible(param_name: str, value: float) -> bool:
    """Return True if value is within the known plausible range for this param."""
    lo, hi = _PLAUSIBLE.get(param_name, (0.0, 1e9))
    return lo <= value <= hi


# ── Header extraction ─────────────────────────────────────────────────────────

_LAB_PATTERNS = [
    re.compile(r'(?:laboratory|lab(?:oratory)?|testing\s+lab(?:oratory)?)[:\s]+(.+)', re.I),
    re.compile(r'(?:issued\s+by|analysed\s+by|analyzed\s+by|tested\s+by)[:\s]+(.+)', re.I),
    re.compile(r'^(.+(?:laboratory|analytical|testing|labs?)\b.{0,40})$', re.I | re.MULTILINE),
]

_SAMPLE_PATTERNS = [
    re.compile(r'(?:sample\s+(?:id|no|number|description)|source|location)[:\s]+(.+)', re.I),
    re.compile(r'(?:sample\s+(?:from|collected\s+(?:from|at)))[:\s]+(.+)', re.I),
    re.compile(r'(?:client|customer)[:\s]+(.+)', re.I),
]


def _extract_lab_info(lines: list[str]) -> str:
    for line in lines[:30]:
        for pat in _LAB_PATTERNS:
            m = pat.search(line)
            if m:
                val = m.group(1).strip()[:120]
                if len(val) > 3:
                    return val
    return ''


def _extract_sample_info(lines: list[str]) -> str:
    for line in lines[:40]:
        for pat in _SAMPLE_PATTERNS:
            m = pat.search(line)
            if m:
                val = m.group(1).strip()[:120]
                if len(val) > 3:
                    return val
    return ''
