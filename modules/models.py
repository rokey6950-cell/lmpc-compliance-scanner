"""
models.py
---------
Database models: users (role-based access), products, and scan/inspection
records that together form the compliance-history repository.
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="inspector")  # 'admin' | 'inspector'
    full_name = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    scans = db.relationship("Scan", backref="inspector", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == "admin"


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    brand = db.Column(db.String(255))
    category = db.Column(db.String(120))
    barcode = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    scans = db.relationship("Scan", backref="product", lazy=True,
                             order_by="desc(Scan.created_at)")


class Scan(db.Model):
    __tablename__ = "scans"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    inspector_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    image_filename = db.Column(db.String(255), nullable=False)
    pdp_width_cm = db.Column(db.Float)
    pdp_height_cm = db.Column(db.Float)

    ocr_text = db.Column(db.Text)
    declarations_json = db.Column(db.Text)   # serialized per-declaration results
    font_analysis_json = db.Column(db.Text)  # serialized font-size analysis
    status = db.Column(db.String(20))        # COMPLIANT | NON_COMPLIANT | NEEDS_REVIEW
    summary_json = db.Column(db.Text)

    location = db.Column(db.String(255))     # store / e-commerce listing / market
    remarks = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def create_default_admin(app):
    """Ensure at least one admin account exists on first run."""
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            admin = User(username="admin", role="admin", full_name="System Administrator")
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()
            print("Default admin created -> username: admin / password: admin123 "
                  "(CHANGE THIS IMMEDIATELY after first login)")
