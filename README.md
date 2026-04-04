# Chemsbury Water Analysis — Setup Guide

## Requirements
- Python 3.8+
- No subscriptions or API keys needed

## Install dependencies
```
pip install -r requirements.txt
```

## Run the backend
```
python app.py
```
Server starts at http://localhost:3000

## Open the website
Just open `chemsbury.html` in your browser.
(Or serve it with any static file server)

## How it works
1. User uploads a water report PDF or image
2. Flask backend receives the file
3. **Digital PDFs** → pdfplumber extracts tables directly (fast, accurate)
4. **Scanned PDFs / images** → PaddleOCR reads the table visually
5. Extracted parameters are sent back to the frontend as JSON
6. Frontend displays results, safety assessment, and filter recommendations

## Notes
- First run may be slow as PaddleOCR downloads its models (~100MB, one time only)
- No GPU needed — runs on CPU fine for water reports (1-5 pages)
- No internet connection needed after first model download
