from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber
import base64
import io
import re
import os
import tempfile
from PIL import Image
import cv2
import numpy as np

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static')
CORS(app, origins="*")

# Config from environment variables (safe for deployment)
PORT = int(os.environ.get('PORT', 3000))
MAX_FILE_SIZE_MB = 10

# ─── EasyOCR (lazy load) ─────────────────────────────────────────────────────
_ocr = None
def get_ocr():
    global _ocr
    if _ocr is None:
        import easyocr
        _ocr = easyocr.Reader(['en'], gpu=False, verbose=False)
    return _ocr

# ─── Parameter key mapping ────────────────────────────────────────────────────
PARAM_MAP = {
    'colour': ['colour', 'color'],
    'turbidity': ['turbidity'],
    'ph': ['ph @', 'ph@', 'ph '],
    'hardness': ['total hardness', 'hardness'],
    'iron': ['iron as fe', 'iron'],
    'chloride': ['chloride as cl', 'chloride'],
    'tds': ['total dissolved solids', 'tds'],
    'calcium': ['calcium as ca', 'calcium'],
    'magnesium': ['magnesium as mg', 'magnesium'],
    'copper': ['copper as cu', 'copper'],
    'manganese': ['manganese as mn', 'manganese'],
    'sulphate': ['sulphate as so4', 'sulphate', 'sulfate'],
    'nitrate': ['nitrate as no3', 'nitrate'],
    'alkalinity': ['total alkalinity', 'alkalinity'],
    'boron': ['boron as b', 'boron'],
    'arsenic': ['arsenic as as', 'arsenic'],
    'h2s': ['sulphide as h2s', 'h2s', 'sulphide', 'sulfide'],
    'fluoride': ['fluoride as f', 'fluoride'],
    'zinc': ['zinc as zn', 'zinc'],
    'aluminium': ['aluminium as al', 'aluminium', 'aluminum'],
    'ammonia': ['ammonia as total ammonia', 'ammonia'],
    'coliform': ['coliforms', 'total coliforms', 'coliform'],
    'ecoli': ['e.coli', 'e. coli', 'ecoli'],
    'chromium': ['chromium as cr', 'chromium'],
    'phenol': ['phenolic compounds', 'phenol'],
    'tss': ['total suspended solids', 'tss'],
    'bod': ['biochemical oxygen demand', 'bod'],
    'cod': ['chemical oxygen demand', 'cod'],
    'lead': ['lead as pb', 'lead'],
    'nitrite': ['nitrite as no2', 'nitrite'],
}

def match_param_key(text):
    t = text.lower().strip()
    for key, aliases in PARAM_MAP.items():
        for alias in aliases:
            if alias in t:
                return key
    return None

def parse_value(text):
    if not text:
        return None
    t = text.strip().lower()
    if any(x in t for x in ['bdl', 'below detectable', 'absent', 'not detected', 'nil', 'nd']):
        return 0.0
    match = re.search(r'\d+\.?\d*', text)
    if match:
        return float(match.group())
    return None

# ─── Image preprocessing for better OCR on JPEG water reports ────────────────
def preprocess_image(img):
    img_np = np.array(img)
    h, w = img_np.shape[:2]

    # Upscale small images — water report photos often need this
    if w < 1800:
        scale = 1800 / w
        img_np = cv2.resize(img_np, (int(w * scale), int(h * scale)),
                            interpolation=cv2.INTER_CUBIC)

    # Convert to grayscale
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

    # Denoise
    gray = cv2.fastNlMeansDenoising(gray, h=10)

    # Sharpen to make text edges crisp
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    gray = cv2.filter2D(gray, -1, kernel)

    # Auto-contrast (histogram equalization)
    gray = cv2.equalizeHist(gray)

    # Back to RGB for EasyOCR
    return Image.fromarray(cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB))

# ─── Strategy 1: pdfplumber for digital PDFs ─────────────────────────────────
def extract_with_pdfplumber(pdf_bytes):
    params = {}
    sample_info = ""
    lab_info = ""

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 3:
                        continue
                    param_text = str(row[1] or '').strip()
                    result_text = str(row[2] or '').strip()
                    key = match_param_key(param_text)
                    if key:
                        val = parse_value(result_text)
                        if val is not None:
                            params[key] = val

            text = page.extract_text() or ''
            if not sample_info:
                for line in text.splitlines():
                    ll = line.lower()
                    if any(x in ll for x in ['sample', 'location', 'source', 'ref no', 'report no']):
                        sample_info = line.strip()
                        break
            if not lab_info:
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                if lines:
                    lab_info = lines[0]

    return params, sample_info, lab_info

# ─── Strategy 2: EasyOCR for scanned PDFs / JPEG images ──────────────────────
def extract_with_easyocr(image_bytes):
    ocr = get_ocr()
    params = {}
    sample_info = ""
    lab_info = ""

    img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    img = preprocess_image(img)  # Upscale + sharpen

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        img.save(tmp.name, 'PNG')  # PNG = lossless, better for OCR
        tmp_path = tmp.name

    try:
        result = ocr.readtext(tmp_path, detail=1, paragraph=False,
                              width_ths=0.7, height_ths=0.7)
    finally:
        os.unlink(tmp_path)

    if not result:
        return params, sample_info, lab_info

    lines = []
    for (bbox, text, conf) in result:
        x_center = (bbox[0][0] + bbox[2][0]) / 2
        y_center = (bbox[0][1] + bbox[2][1]) / 2
        lines.append({'text': text, 'x': x_center, 'y': y_center, 'conf': conf})

    lines.sort(key=lambda l: l['y'])

    if lines:
        lab_info = lines[0]['text']

    # Group into rows by y proximity
    rows = []
    current_row = []
    last_y = None
    for l in lines:
        if last_y is None or abs(l['y'] - last_y) < 18:
            current_row.append(l)
        else:
            if current_row:
                rows.append(sorted(current_row, key=lambda x: x['x']))
            current_row = [l]
        last_y = l['y']
    if current_row:
        rows.append(sorted(current_row, key=lambda x: x['x']))

    for row in rows:
        if len(row) < 2:
            continue
        texts = [c['text'] for c in row]
        # Try col 1 = param, col 2 = result (4-column report: SL, Param, Result, Spec)
        if len(texts) >= 3:
            key = match_param_key(texts[1])
            if key:
                val = parse_value(texts[2])
                if val is not None:
                    params[key] = val
                continue
        # Try col 0 = param, col 1 = result (2-column report)
        key = match_param_key(texts[0])
        if key:
            val = parse_value(texts[1])
            if val is not None:
                params[key] = val

    for l in lines:
        ll = l['text'].lower()
        if any(x in ll for x in ['sample', 'location', 'source', 'ref no']):
            sample_info = l['text']
            break

    return params, sample_info, lab_info

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET'])
def index():
    import os
    # Try multiple possible locations for the HTML file
    base = os.path.dirname(os.path.abspath(__file__))
    possible = [
        os.path.join(base, 'chemsbury.html'),
        os.path.join(base, 'Chemsbury.html'),
        os.path.join(os.getcwd(), 'chemsbury.html'),
        os.path.join(os.getcwd(), 'Chemsbury.html'),
    ]
    logger.info(f"Base dir: {base}, CWD: {os.getcwd()}")
    logger.info(f"Files in dir: {os.listdir(base)}")
    
    html_path = None
    for p in possible:
        if os.path.exists(p):
            html_path = p
            break

    if html_path:
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
        html = html.replace('http://localhost:3000/analyze', '/analyze')
        html = html.replace('http://localhost:3000', '')
        from flask import Response
        return Response(html, mimetype='text/html')
    
    # Show what files are available for debugging
    files = os.listdir(base)
    return f'HTML not found. Files in directory: {files}'

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.get_json()
        if not data or 'file' not in data:
            return jsonify({'error': 'No file provided'}), 400

        file_b64 = data['file']
        file_type = data.get('type', 'image/jpeg')
        raw_bytes = base64.b64decode(file_b64)

        # Validate file size
        size_mb = len(raw_bytes) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            return jsonify({'error': f'File too large ({size_mb:.1f}MB). Maximum is {MAX_FILE_SIZE_MB}MB.'}), 400

        # Validate file type
        allowed_types = ['application/pdf', 'image/jpeg', 'image/png', 'image/jpg']
        if file_type not in allowed_types:
            return jsonify({'error': f'Unsupported file type: {file_type}'}), 400

        params = {}
        sample_info = ""
        lab_info = ""
        method_used = ""

        if file_type == 'application/pdf':
            params, sample_info, lab_info = extract_with_pdfplumber(raw_bytes)
            method_used = 'pdfplumber'
            if not params:
                import fitz
                doc = fitz.open(stream=raw_bytes, filetype='pdf')
                page = doc[0]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_bytes = pix.tobytes('jpeg')
                params, sample_info, lab_info = extract_with_easyocr(img_bytes)
                method_used = 'easyocr_fallback'
        else:
            params, sample_info, lab_info = extract_with_easyocr(raw_bytes)
            method_used = 'easyocr'

        return jsonify({
            'params': params,
            'sampleInfo': sample_info,
            'labInfo': lab_info,
            'confidence': 'high' if len(params) >= 5 else 'medium' if len(params) >= 2 else 'low',
            'notes': f'Extracted {len(params)} parameters using {method_used}',
            'method': method_used
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    logger.info(f"Starting Chemsbury OCR Server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
