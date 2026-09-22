"""
app.py
------
Main Flask application for the LMPC Compliance Scanner.

Run with:  python app.py
Default admin login: admin / admin123  (change after first login)
"""

import os
import json
import uuid
from datetime import datetime

from flask import (Flask, render_template, request, redirect, url_for,
                    flash, send_file, jsonify, abort)
from flask_login import (LoginManager, login_user, logout_user, login_required,
                          current_user)
from werkzeug.utils import secure_filename
from dataclasses import asdict

from modules.models import db, User, Product, Scan, create_default_admin
from modules.ocr_engine import extract_text_and_boxes, analyze_font_sizes
from modules.compliance_rules import (check_declarations, summarize_compliance,
                                       get_min_font_size_mm)
from modules.report_generator import generate_pdf_report

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
REPORT_DIR = os.path.join(BASE_DIR, "reports")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "bmp"}

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("LMPC_SECRET_KEY", "dev-secret-change-me")
database_url = os.environ.get("DATABASE_URL")
if database_url:
    # Render and other providers often supply "postgres://", which SQLAlchemy requires as "postgresql://"
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "instance", "lmpc.db")

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB uploads

os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

# ---------------------------------------------------------------------------
# Database initialisation — runs on first request (works with both
# `python app.py` and Gunicorn / any WSGI server).
# ---------------------------------------------------------------------------
_db_initialised = False

@app.before_request
def _init_db_once():
    global _db_initialised
    if not _db_initialised:
        db.create_all()
        create_default_admin(app)
        _db_initialised = True


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def admin_required(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return func(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_user():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "inspector")
        full_name = request.form.get("full_name", "")
        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "danger")
        else:
            u = User(username=username, role=role, full_name=full_name)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            flash(f"User '{username}' created.", "success")
            return redirect(url_for("dashboard"))
    return render_template("new_user.html")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    total_scans = Scan.query.count()
    compliant = Scan.query.filter_by(status="COMPLIANT").count()
    non_compliant = Scan.query.filter_by(status="NON_COMPLIANT").count()
    needs_review = Scan.query.filter_by(status="NEEDS_REVIEW").count()
    recent_scans = Scan.query.order_by(Scan.created_at.desc()).limit(10).all()
    total_products = Product.query.count()

    return render_template(
        "dashboard.html",
        total_scans=total_scans,
        compliant=compliant,
        non_compliant=non_compliant,
        needs_review=needs_review,
        recent_scans=recent_scans,
        total_products=total_products,
    )


# ---------------------------------------------------------------------------
# Scanning workflow
# ---------------------------------------------------------------------------

@app.route("/scan/new", methods=["GET", "POST"])
@login_required
def new_scan():
    if request.method == "POST":
        product_name = request.form.get("product_name", "").strip()
        brand = request.form.get("brand", "").strip()
        category = request.form.get("category", "").strip()
        barcode = request.form.get("barcode", "").strip()
        location = request.form.get("location", "").strip()
        pdp_width_cm = request.form.get("pdp_width_cm", type=float)
        pdp_height_cm = request.form.get("pdp_height_cm", type=float)
        remarks = request.form.get("remarks", "").strip()

        file = request.files.get("image")
        if not file or file.filename == "":
            flash("Please upload an image of the product label.", "danger")
            return redirect(url_for("new_scan"))
        if not allowed_file(file.filename):
            flash("Unsupported file type. Use PNG/JPG/JPEG/WEBP/BMP.", "danger")
            return redirect(url_for("new_scan"))

        if not product_name:
            flash("Product name is required.", "danger")
            return redirect(url_for("new_scan"))

        # Save image
        ext = file.filename.rsplit(".", 1)[1].lower()
        fname = f"{uuid.uuid4().hex}.{ext}"
        fpath = os.path.join(UPLOAD_DIR, fname)
        file.save(fpath)

        # OCR extraction
        try:
            ocr_result = extract_text_and_boxes(fpath)
        except Exception as e:
            flash(f"OCR processing failed: {e}", "danger")
            return redirect(url_for("new_scan"))

        # Determine PDP area (if dimensions supplied) -> min font size required
        if pdp_width_cm and pdp_height_cm:
            pdp_area_cm2 = pdp_width_cm * pdp_height_cm
        else:
            pdp_area_cm2 = 100  # conservative default slab if not supplied
        min_font_mm = get_min_font_size_mm(pdp_area_cm2)

        font_analysis = analyze_font_sizes(
            ocr_result["words"], ocr_result["image_width_px"], ocr_result["image_height_px"],
            pdp_width_cm=pdp_width_cm, pdp_height_cm=pdp_height_cm,
            min_required_mm=min_font_mm,
        )

        declaration_results = check_declarations(ocr_result["full_text"])
        summary = summarize_compliance(declaration_results, font_analysis["violation_count"])

        # Persist product (find-or-create by name+brand) and scan
        product = Product.query.filter_by(name=product_name, brand=brand).first()
        if not product:
            product = Product(name=product_name, brand=brand, category=category, barcode=barcode)
            db.session.add(product)
            db.session.flush()

        scan = Scan(
            product_id=product.id,
            inspector_id=current_user.id,
            image_filename=fname,
            pdp_width_cm=pdp_width_cm,
            pdp_height_cm=pdp_height_cm,
            ocr_text=ocr_result["full_text"],
            declarations_json=json.dumps([asdict(d) for d in declaration_results]),
            font_analysis_json=json.dumps(font_analysis),
            status=summary["status"],
            summary_json=json.dumps(summary),
            location=location,
            remarks=remarks,
        )
        db.session.add(scan)
        db.session.commit()

        return redirect(url_for("scan_detail", scan_id=scan.id))

    return render_template("new_scan.html")


@app.route("/scan/<int:scan_id>")
@login_required
def scan_detail(scan_id):
    scan = Scan.query.get_or_404(scan_id)
    declarations = json.loads(scan.declarations_json)
    font_analysis = json.loads(scan.font_analysis_json)
    summary = json.loads(scan.summary_json)
    return render_template(
        "scan_detail.html",
        scan=scan,
        product=scan.product,
        declarations=declarations,
        font_analysis=font_analysis,
        summary=summary,
    )


@app.route("/scan/<int:scan_id>/report.pdf")
@login_required
def scan_report_pdf(scan_id):
    scan = Scan.query.get_or_404(scan_id)
    out_path = os.path.join(REPORT_DIR, f"scan_{scan.id}.pdf")
    image_path = os.path.join(UPLOAD_DIR, scan.image_filename)
    generate_pdf_report(scan, scan.product, out_path,
                         image_path=image_path if os.path.exists(image_path) else None)
    return send_file(out_path, as_attachment=True,
                      download_name=f"LMPC_Compliance_Report_{scan.id}.pdf")


@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_file(os.path.join(UPLOAD_DIR, filename))


# ---------------------------------------------------------------------------
# History / search
# ---------------------------------------------------------------------------

@app.route("/history")
@login_required
def history():
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()

    query = Scan.query.join(Product)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(Product.name.ilike(like), Product.brand.ilike(like),
                   Product.barcode.ilike(like), Scan.location.ilike(like))
        )
    if status_filter:
        query = query.filter(Scan.status == status_filter)

    scans = query.order_by(Scan.created_at.desc()).all()
    return render_template("history.html", scans=scans, q=q, status_filter=status_filter)


# ---------------------------------------------------------------------------
# JSON API (for potential mobile client / integrations)
# ---------------------------------------------------------------------------

@app.route("/api/scans/<int:scan_id>")
@login_required
def api_scan_detail(scan_id):
    scan = Scan.query.get_or_404(scan_id)
    return jsonify({
        "id": scan.id,
        "product": scan.product.name,
        "status": scan.status,
        "declarations": json.loads(scan.declarations_json),
        "font_analysis": json.loads(scan.font_analysis_json),
        "summary": json.loads(scan.summary_json),
        "created_at": scan.created_at.isoformat(),
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
