"""
backend/ocr/param_matcher.py

Scans raw OCR text and maps recognised parameter names → float values.
Also extracts lab name and sample info from common header patterns.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Parameter alias table ─────────────────────────────────────────────────────
# key = canonical name (matches water_parameters.parameter_name in DB)
# value = list of regex patterns that match that parameter in lab reports
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

# Compiled for speed
_COMPILED: dict[str, list[re.Pattern]] = {
    k: [re.compile(p, re.IGNORECASE) for p in v]
    for k, v in PARAM_ALIASES.items()
}

# Matches a numeric value (possibly with < or > prefix)
_NUM_RE = re.compile(r'[<>]?\s*(\d+(?:[.,]\d+)?(?:\s*[xX]\s*10\s*[-–^]\s*\d+)?)')


# ── Public API ────────────────────────────────────────────────────────────────
def match_params(text: str) -> tuple[dict, str, str]:
    """
    Returns (params_dict, lab_info, sample_info).
    params_dict maps canonical parameter names → float values.
    """
    lines      = text.splitlines()
    params     = {}
    lab_info   = _extract_lab_info(lines)
    sample_info = _extract_sample_info(lines)

    for line in lines:
        line_lower = line.lower()
        for param_name, patterns in _COMPILED.items():
            if param_name in params:
                continue
            for pat in patterns:
                if pat.search(line_lower):
                    val = _extract_value(line)
                    if val is not None:
                        params[param_name] = val
                    break

    logger.info(f"Matched {len(params)} parameters from {len(lines)} lines")
    return params, lab_info, sample_info


# ── Value extraction ──────────────────────────────────────────────────────────
def _extract_value(line: str) -> Optional[float]:
    """Pull the first numeric value from a line."""
    # Strip the parameter name portion (everything before the first digit/< />)
    m = _NUM_RE.search(line)
    if not m:
        return None
    raw = m.group(1).replace(',', '.').replace(' ', '')
    # Handle scientific notation like "5 x 10^-3"
    sci = re.search(r'(\d+(?:\.\d+)?)\s*[xX]\s*10\s*[-–^]\s*(\d+)', raw)
    if sci:
        try:
            return float(sci.group(1)) * (10 ** -int(sci.group(2)))
        except Exception:
            return None
    try:
        return float(raw)
    except ValueError:
        return None


# ── Header extraction ─────────────────────────────────────────────────────────
_LAB_PATTERNS = [
    re.compile(r'(?:laboratory|lab(?:oratory)?|testing\s+lab(?:oratory)?)[:\s]+(.+)', re.I),
    re.compile(r'(?:issued\s+by|analysed\s+by|tested\s+by)[:\s]+(.+)', re.I),
    re.compile(r'^(.+(?:laboratory|analytical|testing|labs?)\b.{0,40})$', re.I | re.MULTILINE),
]

_SAMPLE_PATTERNS = [
    re.compile(r'(?:sample\s+(?:id|no|number|description)|source|location)[:\s]+(.+)', re.I),
    re.compile(r'(?:sample\s+(?:from|collected\s+(?:from|at)))[:\s]+(.+)', re.I),
    re.compile(r'(?:client|customer)[:\s]+(.+)', re.I),
]


def _extract_lab_info(lines: list[str]) -> str:
    for line in lines[:30]:          # check first 30 lines (report header)
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