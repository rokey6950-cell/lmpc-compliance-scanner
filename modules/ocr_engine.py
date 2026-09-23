"""
ocr_engine.py
-------------
Handles image pre-processing, OCR text extraction (via Tesseract), and a
practical font-size / letter-height estimate derived from OCR bounding
boxes. Font height is reported in pixels and converted to millimetres
using either:
  (a) a user-supplied reference (package width/height in cm), or
  (b) a default assumed scan DPI, clearly flagged as an ESTIMATE.

This mirrors how a real inspection tool would need a physical reference
(a ruler in-frame, or manual package-dimension entry) to get accurate
physical measurements from a photo — pure pixel analysis alone cannot
know real-world scale without one.
"""

import os
import shutil
import cv2
import numpy as np
import pytesseract
from pytesseract import Output

# Auto-detect Tesseract executable on Windows if not already on PATH
if not shutil.which("tesseract"):
    for cand in [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]:
        if os.path.isfile(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            break

DEFAULT_ASSUMED_DPI = 300  # fallback only; used if no physical reference given


def load_and_preprocess(image_path: str, max_dimension: int = 1800):
    """Load image, scale proportionally if needed for high-speed OCR,
    filter noise, and return preprocessed versions."""
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read image at {image_path}")

    orig_h, orig_w = img.shape[:2]
    scale = 1.0
    if max(orig_h, orig_w) > max_dimension:
        scale = max_dimension / max(orig_h, orig_w)
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        img_scaled = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    else:
        img_scaled = img

    gray = cv2.cvtColor(img_scaled, cv2.COLOR_BGR2GRAY)
    # Using bilateralFilter with radius 5 for fast edge preservation
    gray_filtered = cv2.bilateralFilter(gray, 5, 50, 50)
    thresh = cv2.adaptiveThreshold(
        gray_filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    return img, gray_filtered, thresh, orig_w, orig_h, scale


def extract_text_and_boxes(image_path: str) -> dict:
    """
    Run Tesseract OCR and return the full text plus word-level bounding
    boxes (used later for font-height / readability analysis).
    """
    img, gray, thresh, orig_w, orig_h, scale = load_and_preprocess(image_path)

    full_text = pytesseract.image_to_string(gray)
    data = pytesseract.image_to_data(gray, output_type=Output.DICT)

    # Smart fallback: if grayscale produces minimal text (< 50 chars),
    # retry with adaptive thresholding to recover text washed out by glare or low contrast
    if len(full_text.strip()) < 50:
        alt_text = pytesseract.image_to_string(thresh)
        if len(alt_text.strip()) > len(full_text.strip()):
            full_text = alt_text
            data = pytesseract.image_to_data(thresh, output_type=Output.DICT)

    words = []
    inv_scale = 1.0 / scale
    n = len(data["text"])
    for i in range(n):
        txt = data["text"][i].strip()
        conf = data["conf"][i]
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = -1.0
        if txt and conf > 30:
            words.append({
                "text": txt,
                "conf": conf,
                "left": int(data["left"][i] * inv_scale),
                "top": int(data["top"][i] * inv_scale),
                "width": int(data["width"][i] * inv_scale),
                "height": int(data["height"][i] * inv_scale),
            })

    return {
        "full_text": full_text,
        "words": words,
        "image_width_px": orig_w,
        "image_height_px": orig_h,
    }


def analyze_font_sizes(words: list, image_width_px: int, image_height_px: int,
                        pdp_width_cm: float = None, pdp_height_cm: float = None,
                        min_required_mm: float = 1.0):
    """
    Estimate letter heights from OCR word bounding boxes and flag any
    below the minimum required height for the declared PDP area.

    If pdp_width_cm / pdp_height_cm are supplied (recommended — taken from
    the product's declared package dimensions, or a ruler placed in the
    photo), pixel-to-mm conversion is exact for that photo. Otherwise a
    default DPI assumption is used and the result is marked as an
    ESTIMATE with lower confidence.
    """
    if pdp_width_cm and pdp_height_cm and image_width_px and image_height_px:
        px_per_mm = ((image_width_px / (pdp_width_cm * 10)) +
                     (image_height_px / (pdp_height_cm * 10))) / 2
        measurement_basis = "measured"
    else:
        px_per_mm = DEFAULT_ASSUMED_DPI / 25.4
        measurement_basis = "estimated"

    flagged = []
    heights_mm = []
    for w in words:
        if len(w["text"]) < 2:
            continue  # skip stray punctuation / noise
        h_mm = w["height"] / px_per_mm
        heights_mm.append(h_mm)
        if h_mm < min_required_mm:
            flagged.append({
                "text": w["text"],
                "height_mm": round(h_mm, 2),
                "min_required_mm": min_required_mm,
            })

    avg_height_mm = round(sum(heights_mm) / len(heights_mm), 2) if heights_mm else None

    return {
        "measurement_basis": measurement_basis,
        "average_letter_height_mm": avg_height_mm,
        "min_required_mm": min_required_mm,
        "violations": flagged,
        "violation_count": len(flagged),
        "words_analyzed": len(heights_mm),
    }
