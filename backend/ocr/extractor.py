"""
backend/ocr/extractor.py

Extraction pipeline:
  - Digital PDFs  → pdfplumber  (fast, accurate)
  - Images / scanned PDFs → pytesseract (lightweight, no torch dependency)
"""
import io
import logging
import re

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
            'params':      dict[str, float|None],
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
    text_chunks = []

    # Try pdfplumber first (digital PDFs)
    try:
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page in pdf.pages:
                # Extract tables
                for table in page.extract_tables():
                    for row in table:
                        clean = [str(c).strip() if c else '' for c in row]
                        text_chunks.append('\t'.join(clean))
                # Extract plain text as fallback
                page_text = page.extract_text()
                if page_text:
                    text_chunks.append(page_text)
    except Exception as e:
        logger.warning(f"pdfplumber failed: {e}")

    if text_chunks:
        full_text = '\n'.join(text_chunks)
        params, lab_info, sample_info = match_params(full_text)
        if params:
            return {
                'params':      params,
                'lab_info':    lab_info,
                'sample_info': sample_info,
                'confidence':  'high',
                'method_used': 'pdfplumber',
                'notes':       '',
            }

    # Fallback: render PDF pages as images and OCR
    if FITZ_AVAILABLE and OCR_AVAILABLE:
        logger.info("pdfplumber found no tables — falling back to OCR")
        return _ocr_pdf_pages(raw_bytes)

    return _empty_result(notes="No text could be extracted from this PDF.")


def _ocr_pdf_pages(raw_bytes: bytes) -> dict:
    """Render each PDF page as an image and run pytesseract."""
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    all_text = []

    for page in doc:
        mat  = fitz.Matrix(2.0, 2.0)          # 2× zoom → ~144 dpi
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img  = preprocess_image(img)
        text = pytesseract.image_to_string(img, config='--psm 6')
        all_text.append(text)

    doc.close()
    full_text = '\n'.join(all_text)
    params, lab_info, sample_info = match_params(full_text)

    return {
        'params':      params,
        'lab_info':    lab_info,
        'sample_info': sample_info,
        'confidence':  'medium' if params else 'low',
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
        text = pytesseract.image_to_string(img, config='--psm 6')

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