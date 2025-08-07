from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.String(20), nullable=False)     # Ej: "2025-08-06"
    hora = db.Column(db.String(10), nullable=False)      # Ej: "08:00"
    reserved = db.Column(db.Boolean, default=False)
    reserved_by = db.Column(db.String(100), nullable=True)
    category = db.Column(db.String(50), nullable=True)