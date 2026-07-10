"""
Market Lens — OCR Fallback Cascade (Phase 10)
Four-step: (1) EDGAR JSON/structured text, (2) pdfplumber, (3) Tesseract, (4) manual placeholder.
Used as fallback when primary EDGAR/Form 4 parse fails.

Requires: pdfplumber, opencv-python, pytesseract; Tesseract Windows executable
installed to C:\\Program Files\\Tesseract-OCR\\tesseract.exe (or set TESSERACT_CMD).
"""
from pathlib import Path
from typing import Optional, Tuple

# Ensure Tesseract path is set (config sets pytesseract.tesseract_cmd on import)
def _ensure_tesseract_cmd() -> None:
    try:
        import pytesseract
        from market_lens import config  # noqa: F401 — sets tesseract_cmd
        _ = config
    except Exception:
        pass

# Step 1: Structured/JSON — caller provides text if already extracted from EDGAR
# Step 2: pdfplumber
# Step 3: pytesseract (+ optional OpenCV for image preprocess)
# Step 4: return (None, "manual") to signal manual review


def extract_text_pdfplumber(file_path: Path) -> Optional[str]:
    """Extract text from PDF using pdfplumber. Returns None on failure."""
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            parts = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
            return "\n".join(parts) if parts else None
    except Exception:
        return None


def extract_text_tesseract(file_path: Path) -> Optional[str]:
    """Extract text from PDF/image using pytesseract. Returns None on failure."""
    _ensure_tesseract_cmd()
    try:
        import pytesseract
        from PIL import Image
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            try:
                import pdf2image
                images = pdf2image.convert_from_path(file_path)
            except Exception:
                return None
            parts = []
            for img in images:
                text = pytesseract.image_to_string(img)
                if text:
                    parts.append(text)
            return "\n".join(parts) if parts else None
        if suffix in (".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
            img = Image.open(file_path)
            return pytesseract.image_to_string(img) or None
    except Exception:
        pass
    return None


def extract_text_cascade(
    file_path: Optional[Path] = None,
    edgar_text: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """
    Four-step cascade. Returns (extracted_text, source).
    source is one of: "edgar", "pdfplumber", "tesseract", "manual".

    - If edgar_text is provided and non-empty, return (edgar_text, "edgar").
    - Else if file_path points to a PDF, try pdfplumber then tesseract.
    - Else return (None, "manual").
    """
    if edgar_text and edgar_text.strip():
        return (edgar_text.strip(), "edgar")

    if not file_path or not file_path.exists():
        return (None, "manual")

    text = extract_text_pdfplumber(file_path)
    if text and text.strip():
        return (text.strip(), "pdfplumber")

    text = extract_text_tesseract(file_path)
    if text and text.strip():
        return (text.strip(), "tesseract")

    return (None, "manual")
