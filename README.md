# LMPC Compliance Scanner

A working prototype for **SIH Problem Statement 26034** — a software system to
check compliance of packaged commodities under the **Legal Metrology
(Packaged Commodities) Rules, 2011**, by scanning product labels and images.

Built for: Ministry of Consumer Affairs, Food & Public Distribution —
Department of Consumer Affairs (DoCA).

---

## 1. What this prototype does

1. **Upload** a photo of a product's principal display panel (PDP).
2. **OCR extraction** (Tesseract + OpenCV pre-processing) pulls all text
   and per-word bounding boxes off the label.
3. **Rule-based compliance engine** checks the extracted text against the
   mandatory declarations in **Rule 6** of the LMPC Rules, 2011:
   - Manufacturer/packer/importer name & address
   - Common/generic name of the commodity (flagged for manual confirmation)
   - Net quantity
   - Month & year of manufacture/packing/import
   - MRP (and the "inclusive of all taxes" phrase)
   - Consumer care details (phone/toll-free/email)
   - Country of origin (for imports)
   - Best before / use-by date (where applicable)
4. **Font-size / readability analysis** estimates letter height (mm) from
   OCR bounding boxes and flags text below the minimum required height for
   the declared PDP area (per the Rules' font-size schedule).
5. **Compliance verdict**: `COMPLIANT` / `NON_COMPLIANT` / `NEEDS_REVIEW`.
6. **PDF report generation** — a formatted, downloadable inspection report
   per scan.
7. **Dashboard** — totals, recent scans, compliance breakdown.
8. **Searchable repository/history** of every scan (by product, brand,
   barcode, location, status).
9. **Role-based access** (Admin / Inspector) with secure password hashing.

---

## 2. Architecture

```
lmpc_compliance/
├── app.py                     # Flask application & routes
├── modules/
│   ├── models.py               # SQLAlchemy models (User, Product, Scan)
│   ├── ocr_engine.py           # Image preprocessing + Tesseract OCR + font-size analysis
│   ├── compliance_rules.py     # Rule 6 declaration checks (data-driven, editable)
│   └── report_generator.py     # ReportLab PDF report builder
├── templates/                  # Jinja2 + Bootstrap 5 UI
├── static/css/style.css        # Custom styling
├── uploads/                    # Stored label images
├── reports/                    # Generated PDF reports
├── instance/lmpc.db            # SQLite database (auto-created)
└── requirements.txt
```

**Stack:** Python 3 / Flask / SQLAlchemy (SQLite by default, swappable for
Postgres/MySQL in production) / Flask-Login for auth / OpenCV + Tesseract
OCR / ReportLab for PDF generation / Bootstrap 5 for the UI.

**Design notes:**
- `compliance_rules.py` keeps every legal threshold (which declarations are
  mandatory, their rule references, and the PDP-area → minimum font-size
  slabs) in one `RULE_CONFIG` dictionary, so a Legal Metrology domain
  expert can review/update figures without touching detection logic —
  important since these should be verified against the authoritative Rules
  text and any amendments before departmental use.
- Font-size measurement is most accurate when the inspector enters the
  physical **PDP width/height (cm)** at scan time (recommended field in the
  form) — this lets the tool convert OCR pixel heights to real millimetres.
  Without it, the tool falls back to an assumed-DPI estimate and clearly
  labels the result "estimated" rather than "measured" everywhere it's shown
  (UI and PDF report), so it's never silently treated as an enforceable
  measurement.
- "Common/generic name of the commodity" is intentionally never
  auto-approved — it is always flagged for a human inspector to confirm,
  since distinguishing a valid generic name from a brand/marketing phrase
  reliably needs product-category context that a generic OCR+regex layer
  cannot safely infer.

---

## 3. Setup & running locally

```bash
cd lmpc_compliance
python3 -m venv venv && source venv/bin/activate     # optional but recommended
pip install -r requirements.txt

# System dependency (OCR engine) — install if not already present:
#   Ubuntu/Debian: sudo apt-get install tesseract-ocr
#   macOS:         brew install tesseract
#   Windows:       https://github.com/UB-Mannheim/tesseract/wiki

python app.py
```

The app starts at **http://localhost:5000**.

On first run it creates a SQLite database and a default admin account:

```
username: admin
password: admin123   (change immediately — use "Add User" to create real
                       accounts, then remove/rotate the default admin)
```

---

## 4. Using it

1. Log in → **New Scan**.
2. Fill in product name/brand/category, the inspection location, and
   (recommended) the PDP width & height in cm.
3. Upload a clear, flat, well-lit photo of the label's front panel.
4. Submit → the system OCRs the image, runs the compliance checklist and
   font-size analysis, and shows a full breakdown with an overall verdict.
5. Download the **PDF report** for the case file, or find it again later
   from **History** (searchable by product/brand/barcode/location/status).

---

## 5. Extending toward a production system

This prototype demonstrates the full pipeline end-to-end on a single
instance/SQLite setup. To take it further:

- **Accuracy**: fine-tune OCR with a label-specific model (e.g. a custom
  Tesseract language pack or a fine-tuned layout-aware model such as
  LayoutLMv3) trained on real Indian packaged-commodity labels; add barcode
  /QR scanning to auto-pull declared product master data for
  cross-verification against the label.
- **Physical font-size accuracy**: support a reference marker (e.g. a
  printed calibration square or the barcode's known physical width) in-frame
  so millimetre conversion doesn't rely on manually entered PDP dimensions.
- **Scale**: move from SQLite to PostgreSQL, add object storage (S3/GCS) for
  images, and containerize (Docker) for departmental deployment.
- **Coverage**: extend `RULE_CONFIG` for category-specific rules (e.g.
  additional declarations for cosmetics, e-commerce listing–specific
  requirements under Rule 6 read with e-commerce guidelines).
- **Mobile**: wrap the same Flask API (`/api/scans/<id>`) with a native or
  PWA mobile client for field inspectors to scan on-site.
- **E-commerce crawling**: add a scheduled scraper module to pull listing
  images from e-commerce platforms for proactive, large-scale compliance
  sweeps rather than manual upload only.

---

## 6. Legal disclaimer (important)

This is a **decision-support prototype**, not a substitute for statutory
determination. All flagged violations are a system-generated preliminary
assessment; final determination of non-compliance under the Legal
Metrology Act, 2009 and the LMPC Rules, 2011 rests with the competent
Legal Metrology authority. The rule thresholds encoded here should be
verified against the current, amended text of the Rules by a domain
expert before any enforcement use.
