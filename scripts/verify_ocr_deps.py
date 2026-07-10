"""
Verify OCR dependencies before using processing/ocr.py:
  pdfplumber, opencv-python, pytesseract + Tesseract executable.
Run from project root: python scripts/verify_ocr_deps.py
"""
import sys
from pathlib import Path

# Project root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main():
    errors = []
    # 1. pdfplumber
    try:
        import pdfplumber
        print("[OK] pdfplumber")
    except Exception as e:
        errors.append(f"pdfplumber: {e}")

    # 2. opencv-python
    try:
        import cv2
        assert cv2.__version__
        print("[OK] opencv-python")
    except Exception as e:
        errors.append(f"opencv-python: {e}")

    # 3. pytesseract + Tesseract executable (config sets tesseract_cmd)
    try:
        from market_lens import config
        import pytesseract
        # Use config's path if set
        if getattr(pytesseract.pytesseract, "tesseract_cmd", None):
            v = pytesseract.get_tesseract_version()
            print(f"[OK] pytesseract + Tesseract (version: {v})")
        else:
            v = pytesseract.get_tesseract_version()
            print(f"[OK] pytesseract + Tesseract (version: {v})")
    except Exception as e:
        errors.append(f"pytesseract/Tesseract: {e}")

    if errors:
        print("Errors:", errors)
        sys.exit(1)
    print("All three OCR dependencies OK.")

if __name__ == "__main__":
    main()
