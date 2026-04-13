"""
backend/ocr/preprocessor.py

Prepares images for OCR: resize, greyscale, denoise, threshold.
Uses only Pillow + opencv-headless (no torch).
"""
import logging

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def preprocess_image(img: Image.Image) -> Image.Image:
    """
    Takes a PIL Image, returns a cleaned PIL Image ready for tesseract.
    Steps: upscale if small → greyscale → denoise → adaptive threshold → deskew
    """
    try:
        # 1. Upscale if too small (tesseract works best at ~300dpi / 2000px wide)
        w, h = img.size
        if w < 1500:
            scale = 1500 / w
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        # 2. Convert to OpenCV greyscale
        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)

        # 3. Denoise
        cv_img = cv2.fastNlMeansDenoising(cv_img, h=10)

        # 4. Adaptive threshold (handles uneven lighting)
        cv_img = cv2.adaptiveThreshold(
            cv_img, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31, 11
        )

        # 5. Deskew
        cv_img = _deskew(cv_img)

        return Image.fromarray(cv_img)

    except Exception as exc:
        logger.warning(f"Preprocessing failed, using original: {exc}")
        return img


def _deskew(img: np.ndarray) -> np.ndarray:
    """Rotate image to straighten text."""
    try:
        coords = np.column_stack(np.where(img < 128))
        if len(coords) < 50:
            return img
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) < 0.5:          # skip tiny corrections
            return img
        h, w = img.shape
        centre = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(centre, angle, 1.0)
        return cv2.warpAffine(
            img, M, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE
        )
    except Exception:
        return img