"""
backend/ocr/extractor.py

Extraction pipeline:
  - Digital PDFs  → pdfplumber  (fast, accurate — primary path)
  - Images / scanned PDFs → pytesseract (lightweight, no torch dependency)

Accuracy improvements:
  - pdfplumber: extracts BOTH tables AND plain text, feeds both to matcher
  - Table rows serialised as TSV so param_matcher can use column position
  - pytesseract: --psm 6 (assume uniform block) + --oem 3 (LSTM)
  - Image preprocessing applied before OCR
"""
import io
import logging

import pdfplumber
from PIL import Image

from backend.ocr.preprocessor import preprocess_image
from backend.ocr.param_matcher import match_params

logger = logging.getLogger(__name__)

# ── pytesseract import with graceful fallback ─────────────────────────────────
try:
    import pytesseract
    OCR_AVAILABLE = True
    logger.info("pytesseract loaded successfully")
except ImportError:
    OCR_AVAILABLE = False
    logger.warning("pytesseract not available — scanned PDF/image OCR disabled")

# ── PyMuPDF for PDF→image conversion ─────────────────────────────────────────
try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False
    logger.warning("PyMuPDF not available — scanned PDF fallback disabled")


# ── Magic-byte validation ─────────────────────────────────────────────────────
_MAGIC = {
    'application/pdf': b'%PDF',
    'image/jpeg':      b'\xff\xd8\xff',
    'image/jpg':       b'\xff\xd8\xff',
    'image/png':       b'\x89PNG',
}


def validate_upload(raw_bytes: bytes, claimed_type: str) -> tuple[bool, str]:
    expected = _MAGIC.get(claimed_type)
    if expected and not raw_bytes.startswith(expected):
        return False, f"File content does not match declared type ({claimed_type})."
    return True, ""


# ── Main entry point ──────────────────────────────────────────────────────────
def extract_params(raw_bytes: bytes, mime_type: str) -> dict:
    """
    Returns:
        {
            'params':      dict[str, float],
            'lab_info':    str,
            'sample_info': str,
            'confidence':  'high'|'medium'|'low',
            'method_used': str,
            'notes':       str,
        }
    """
    try:
        if mime_type == 'application/pdf':
            return _extract_pdf(raw_bytes)
        else:
            return _extract_image(raw_bytes)
    except Exception as exc:
        logger.error(f"Extraction failed: {exc}", exc_info=True)
        return _empty_result(notes=f"Extraction error: {exc}")


# ── PDF extraction ────────────────────────────────────────────────────────────

def _extract_pdf(raw_bytes: bytes) -> dict:
    """
    Two-pass pdfplumber extraction:
      Pass 1 — structured table rows (TSV): highest accuracy for digital PDFs
      Pass 2 — raw page text: catches parameters not inside formal table cells

    Only falls back to OCR if pdfplumber finds zero text at all (scanned PDF).
    """
    table_lines: list[str] = []
    text_lines:  list[str] = []

    try:
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page in pdf.pages:
                # ── Pass 1: structured tables ─────────────────────────────────
                for table in page.extract_tables():
                    for row in table:
                        # Each cell: coerce None → '', strip whitespace
                        clean = [str(c).strip() if c is not None else '' for c in row]
                        # Skip rows that are entirely empty
                        if any(clean):
                            table_lines.append('\t'.join(clean))

                # ── Pass 2: raw text ──────────────────────────────────────────
                page_text = page.extract_text()
                if page_text:
                    text_lines.extend(page_text.splitlines())

    except Exception as e:
        logger.warning(f"pdfplumber failed: {e}")

    # Feed table lines FIRST (higher column-position accuracy),
    # then plain text lines as a catch-all.
    combined = table_lines + text_lines

    if combined:
        full_text = '\n'.join(combined)
        params, lab_info, sample_info = match_params(full_text)

        if params:
            logger.info(
                "pdfplumber extracted %d params (%d table rows, %d text lines)",
                len(params), len(table_lines), len(text_lines)
            )
            return {
                'params':      params,
                'lab_info':    lab_info,
                'sample_info': sample_info,
                'confidence':  'high',
                'method_used': 'pdfplumber',
                'notes':       '',
            }

        # pdfplumber got text but matcher found nothing — still return what
        # we have rather than bailing out to OCR (which would be worse for digital)
        if text_lines:
            logger.warning("pdfplumber found text but no params matched; returning empty params")
            return {
                'params':      {},
                'lab_info':    lab_info,
                'sample_info': sample_info,
                'confidence':  'low',
                'method_used': 'pdfplumber (no params matched)',
                'notes':       'Could not extract parameter values. Check that the PDF contains a standard water quality table.',
            }

    # No text at all → scanned PDF, fall back to OCR
    if FITZ_AVAILABLE and OCR_AVAILABLE:
        logger.info("pdfplumber found no text — falling back to pytesseract OCR")
        return _ocr_pdf_pages(raw_bytes)

    return _empty_result(notes="No text could be extracted from this PDF.")


def _ocr_pdf_pages(raw_bytes: bytes) -> dict:
    """Render each PDF page as an image and run pytesseract."""
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    all_text: list[str] = []

    for page_num, page in enumerate(doc):
        # 2× zoom → ~144 dpi, good balance of speed vs accuracy
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img = preprocess_image(img)

        # --psm 6: assume a single uniform block of text (good for tables)
        # --oem 3: use LSTM engine
        text = pytesseract.image_to_string(img, config='--psm 6 --oem 3')
        logger.debug("OCR page %d: %d chars", page_num + 1, len(text))
        all_text.append(text)

    doc.close()

    full_text = '\n'.join(all_text)
    params, lab_info, sample_info = match_params(full_text)

    confidence = 'medium' if params else 'low'

    return {
        'params':      params,
        'lab_info':    lab_info,
        'sample_info': sample_info,
        'confidence':  confidence,
        'method_used': 'pytesseract (scanned PDF)',
        'notes':       'Scanned PDF — accuracy depends on scan quality.',
    }


# ── Image extraction ──────────────────────────────────────────────────────────

def _extract_image(raw_bytes: bytes) -> dict:
    if not OCR_AVAILABLE:
        return _empty_result(notes="OCR engine not available on this server.")

    try:
        img  = Image.open(io.BytesIO(raw_bytes)).convert('RGB')
        img  = preprocess_image(img)

        # --psm 6: uniform block; --oem 3: LSTM engine
        text = pytesseract.image_to_string(img, config='--psm 6 --oem 3')
        logger.debug("Image OCR: %d chars extracted", len(text))

        params, lab_info, sample_info = match_params(text)

        return {
            'params':      params,
            'lab_info':    lab_info,
            'sample_info': sample_info,
            'confidence':  'medium' if params else 'low',
            'method_used': 'pytesseract',
            'notes':       '',
        }
    except Exception as exc:
        logger.error(f"Image OCR failed: {exc}", exc_info=True)
        return _empty_result(notes=f"Image processing error: {exc}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_result(notes: str = '') -> dict:
    return {
        'params':      {},
        'lab_info':    '',
        'sample_info': '',
        'confidence':  'low',
        'method_used': 'none',
        'notes':       notes,
    }
