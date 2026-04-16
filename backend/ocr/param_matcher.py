"""
backend/ocr/param_matcher.py

Normalizes OCR text and extracts parameter/value pairs from variable lab-report
tables. The matcher is intentionally heuristic-based and lightweight so it stays
stable across real-world report formats.
"""
import logging
import re

logger = logging.getLogger(__name__)


PARAM_KEYWORDS: dict[str, list[str]] = {
    "ph": ["ph", "potential of hydrogen"],
    "tds": ["tds", "total dissolved solids", "dissolved solids"],
    "hardness": ["total hardness", "hardness", "caco3", "as caco3"],
    "iron": ["iron", "fe", "ferrous", "ferric"],
    "chloride": ["chloride", "chlorides", "cl"],
    "turbidity": ["turbidity", "ntu"],
    "conductivity": ["conductivity", "electrical conductivity", "ec"],
    "alkalinity": ["alkalinity", "total alkalinity"],
    "nitrate": ["nitrate", "no3"],
    "sulphate": ["sulphate", "sulphates", "sulfate", "sulfates", "so4"],
    "fluoride": ["fluoride", "fluorides", "fluorine"],
    "residual_chlorine": ["residual chlorine", "chlorine residual", "as rc", "rc"],
    "acidity": ["acidity"],
    "calcium": ["calcium"],
    "magnesium": ["magnesium"],
    "colour": ["colour", "color", "apparent colour", "apparent color", "hazen"],
    "odour": ["odour", "odor"],
}

UNIT_PATTERNS = [
    r"mg/l",
    r"ppm",
    r"ntu",
    r"us/cm",
    r"µs/cm",
    r"ms/cm",
    r"hazen",
]

HEADER_SKIP_WORDS = {
    "sl no",
    "s no",
    "characteristics",
    "characteristic",
    "unit",
    "test method",
    "acceptable",
    "permissible",
    "result",
    "remarks",
    "limit",
}

METHOD_HINTS = ("is 3025", "part", "reaffirmed", "method", "apha")

NUM_RE = re.compile(r"(?<![A-Za-z0-9])([<>]?\s*-?\d+(?:[.,]\d+)?(?:\s*(?:x|X|x10|X10|[xX]\s*10)\s*(?:\^)?\s*-?\d+)?)")

LAB_PATTERNS = [
    re.compile(r"(?:laboratory|lab(?:oratory)?|testing\s+lab(?:oratory)?)[:\s]+(.+)", re.I),
    re.compile(r"(?:issued\s+by|analysed\s+by|tested\s+by)[:\s]+(.+)", re.I),
    re.compile(r"^(.+(?:laboratory|analytical|testing|labs?)\b.{0,40})$", re.I | re.MULTILINE),
]

SAMPLE_PATTERNS = [
    re.compile(r"(?:sample\s+(?:id|no|number|description)|source|location)[:\s]+(.+)", re.I),
    re.compile(r"(?:sample\s+(?:from|collected\s+(?:from|at)))[:\s]+(.+)", re.I),
    re.compile(r"(?:client|customer)[:\s]+(.+)", re.I),
]


def normalize_text(text: str) -> str:
    text = text.lower()
    text = text.replace("°", " ").replace("º", " ").replace("@", " ")
    text = text.replace("(", " ").replace(")", " ")
    text = text.replace("[", " ").replace("]", " ")
    text = text.replace("{", " ").replace("}", " ")
    text = text.replace("|", " ")
    text = text.replace("µ", "u")
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[,;:]+", " ", text)
    text = re.sub(r"[^a-z0-9.+<>\-\s/\n\t]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = _drop_temperature_tokens(text)
    return text.strip()


def match_params(text: str) -> dict:
    raw_text = (text or "").strip()
    raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    norm_lines = [normalize_text(line) for line in raw_lines]
    normalized_text = "\n".join(line for line in norm_lines if line)

    params: dict[str, float] = {}
    extracted_units: dict[str, str] = {}
    matched_rows: dict[str, str] = {}
    match_scores: dict[str, int] = {}

    idx = 0
    while idx < len(raw_lines):
        raw_line = raw_lines[idx]
        norm_line = norm_lines[idx]
        if _looks_like_header(norm_line):
            idx += 1
            continue

        match = _match_parameter(norm_line)
        if not match:
            idx += 1
            continue

        param_name, score = match
        block_raw = [raw_line]
        next_idx = idx + 1
        while next_idx < len(raw_lines) and len(block_raw) < 5:
            next_norm = norm_lines[next_idx]
            if _match_parameter(next_norm):
                break
            if next_norm:
                block_raw.append(raw_lines[next_idx])
            next_idx += 1

        value, unit = _extract_value_from_block(block_raw)
        if value is None:
            idx = next_idx
            continue

        if param_name in match_scores and match_scores[param_name] > score:
            idx = next_idx
            continue

        params[param_name] = value
        match_scores[param_name] = score
        matched_rows[param_name] = " | ".join(block_raw)
        if unit:
            extracted_units[param_name] = unit
        idx = next_idx

    logger.info("Matched %s parameters from %s OCR lines", len(params), len(raw_lines))
    return {
        "params": params,
        "lab_info": _extract_lab_info(raw_lines),
        "sample_info": _extract_sample_info(raw_lines),
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "extracted_units": extracted_units,
        "matched_rows": matched_rows,
    }


def _looks_like_header(norm_line: str) -> bool:
    if not norm_line:
        return True
    for word in HEADER_SKIP_WORDS:
        pattern = rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])"
        if re.search(pattern, norm_line):
            return True
    return False


def _match_parameter(norm_line: str) -> tuple[str, int] | None:
    best: tuple[str, int] | None = None
    for canonical, aliases in PARAM_KEYWORDS.items():
        for alias in aliases:
            alias_norm = normalize_text(alias)
            if not alias_norm:
                continue
            pattern = rf"(?<![a-z0-9]){re.escape(alias_norm)}(?![a-z0-9])"
            if re.search(pattern, norm_line):
                score = len(alias_norm)
                if best is None or score > best[1]:
                    best = (canonical, score)
    return best


def _extract_value_from_block(raw_lines: list[str]) -> tuple[float | None, str]:
    unit = ""
    for line in raw_lines:
        unit = unit or _extract_unit(line)

    useful_lines = [
        line for line in raw_lines
        if not _looks_like_method_line(normalize_text(line))
    ] or raw_lines

    for line in reversed(useful_lines):
        value = _extract_rightmost_numeric(_strip_temperature(line))
        if value is not None:
            return value, unit

    raw_line = raw_lines[0]
    norm_line = normalize_text(raw_line)
    raw_cells = _split_row(raw_line)
    norm_cells = _split_row(norm_line)
    param_cell_idx = _find_parameter_cell(norm_cells)
    search_cells = raw_cells[param_cell_idx + 1:] if param_cell_idx is not None else raw_cells
    unit = ""

    for cell in search_cells:
        unit = unit or _extract_unit(cell)

    for cell in reversed(search_cells):
        value = _extract_numeric(cell)
        if value is not None:
            return value, unit or _extract_unit(cell)

    value = _extract_rightmost_numeric(_strip_temperature(raw_line))
    return value, unit or _extract_unit(raw_line)


def _looks_like_method_line(norm_line: str) -> bool:
    return any(hint in norm_line for hint in METHOD_HINTS)


def _split_row(line: str) -> list[str]:
    cells = re.split(r"\t+|\s{2,}|[|]+", line)
    return [cell.strip() for cell in cells if cell and cell.strip()]


def _find_parameter_cell(cells: list[str]) -> int | None:
    best_idx = None
    best_score = -1
    for idx, cell in enumerate(cells):
        match = _match_parameter(cell)
        if match and match[1] > best_score:
            best_idx = idx
            best_score = match[1]
    return best_idx


def _strip_temperature(text: str) -> str:
    return _drop_temperature_tokens(text)


def _drop_temperature_tokens(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        tokens = line.split()
        kept = []
        i = 0
        while i < len(tokens):
            if (
                tokens[i].lower() == "at"
                and i + 2 < len(tokens)
                and re.fullmatch(r"\d+(?:\.\d+)?", tokens[i + 1])
                and tokens[i + 2].lower() == "c"
            ):
                i += 3
                continue
            if (
                i + 1 < len(tokens)
                and re.fullmatch(r"\d+(?:\.\d+)?", tokens[i])
                and tokens[i + 1].lower() == "c"
            ):
                i += 2
                continue
            kept.append(tokens[i])
            i += 1
        cleaned_lines.append(" ".join(kept))
    return "\n".join(cleaned_lines)


def _extract_numeric(text: str) -> float | None:
    match = NUM_RE.search(text)
    if not match:
        return None

    raw = match.group(1).replace(",", ".").replace(" ", "")
    sci = re.match(r"([<>-]?\d+(?:\.\d+)?)[xX]10\^?(-?\d+)", raw)
    if sci:
        try:
            return float(sci.group(1).lstrip("<>")) * (10 ** int(sci.group(2)))
        except ValueError:
            return None

    raw = raw.lstrip("<>")
    try:
        return float(raw)
    except ValueError:
        return None


def _extract_rightmost_numeric(text: str) -> float | None:
    matches = list(NUM_RE.finditer(text))
    for match in reversed(matches):
        value = _extract_numeric(match.group(0))
        if value is not None:
            return value
    return None


def _extract_unit(text: str) -> str:
    norm = normalize_text(text)
    for pattern in UNIT_PATTERNS:
        match = re.search(rf"(?<![a-z0-9])({pattern})(?![a-z0-9])", norm)
        if match:
            return match.group(1).upper().replace("US/CM", "uS/cm").replace("MS/CM", "mS/cm")
    return ""


def _extract_lab_info(lines: list[str]) -> str:
    for line in lines[:30]:
        for pattern in LAB_PATTERNS:
            match = pattern.search(line)
            if match:
                value = match.group(1).strip()[:120]
                if len(value) > 3:
                    return value
    return ""


def _extract_sample_info(lines: list[str]) -> str:
    for line in lines[:40]:
        for pattern in SAMPLE_PATTERNS:
            match = pattern.search(line)
            if match:
                value = match.group(1).strip()[:120]
                if len(value) > 3:
                    return value
    return ""
