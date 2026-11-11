import os
import secrets
from datetime import datetime, timezone

import cloudinary
import cloudinary.uploader
import psycopg
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
CORS(app, origins=os.getenv("FRONTEND_ORIGIN", "*").split(","))
DATABASE_URL = os.environ["DATABASE_URL"]

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)


def db():
    return psycopg.connect(DATABASE_URL, sslmode="require", row_factory=psycopg.rows.dict_row)


def initialize_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS bookings (
            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL,
            service TEXT NOT NULL, date DATE NOT NULL, time TEXT NOT NULL, location TEXT NOT NULL DEFAULT '',
            package TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', payment_method TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_method TEXT NOT NULL DEFAULT ''")


@app.get("/api/health")
def health():
    return jsonify(status="ok")


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    name, email, password = (str(data.get(k, "")).strip() for k in ("name", "email", "password"))
    if not name or "@" not in email or len(password) < 8:
        return jsonify(error="Enter your name, a valid email, and a password with at least 8 characters."), 400
    token = secrets.token_urlsafe(32)
    try:
        with db() as conn:
            user = conn.execute("INSERT INTO users(name,email,password_hash) VALUES (%s,%s,%s) RETURNING id,name,email",
                                (name, email.lower(), generate_password_hash(password))).fetchone()
            conn.execute("INSERT INTO sessions(token,user_id) VALUES (%s,%s)", (token, user["id"]))
    except psycopg.errors.UniqueViolation:
        return jsonify(error="An account with this email already exists."), 409
    return jsonify(token=token, user={"name": user["name"], "email": user["email"]}), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    with db() as conn:
        user = conn.execute("SELECT id,name,email,password_hash FROM users WHERE email=%s", (str(data.get("email", "")).lower(),)).fetchone()
        if not user or not check_password_hash(user["password_hash"], str(data.get("password", ""))):
            return jsonify(error="Email or password is incorrect."), 401
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessions(token,user_id) VALUES (%s,%s)", (token, user["id"]))
    return jsonify(token=token, user={"name": user["name"], "email": user["email"]})


@app.post("/api/bookings")
def create_booking():
    data = request.get_json(silent=True) or {}
    required = ("name", "email", "phone", "service", "date", "time", "package")
    if any(not str(data.get(key, "")).strip() for key in required):
        return jsonify(error="Please complete all required booking fields."), 400
    with db() as conn:
        row = conn.execute("""INSERT INTO bookings(name,email,phone,service,date,time,location,package,notes,payment_method)
            VALUES (%(name)s,%(email)s,%(phone)s,%(service)s,%(date)s,%(time)s,%(location)s,%(package)s,%(notes)s,%(payment_method)s)
            RETURNING id,name,email,phone,service,date,time,location,package,notes,payment_method,status,created_at""",
            {**data, "location": data.get("location", ""), "notes": data.get("notes", ""),
             "payment_method": data.get("payment_method", "")}).fetchone()
    booking = dict(row)
    booking["id"] = f"BK-{booking['id']}"
    booking["date"] = str(booking["date"])
    booking["createdAt"] = booking.pop("created_at").isoformat()
    return jsonify(booking=booking), 201


@app.post("/api/images")
def upload_image():
    if not os.getenv("STUDIO_UPLOAD_KEY") or request.headers.get("X-Upload-Key") != os.getenv("STUDIO_UPLOAD_KEY"):
        return jsonify(error="Studio upload authorization required."), 401
    image = request.files.get("image")
    if not image:
        return jsonify(error="Choose an image to upload."), 400
    if image.mimetype not in {"image/jpeg", "image/png", "image/webp"}:
        return jsonify(error="Upload a JPEG, PNG, or WebP image."), 400
    result = cloudinary.uploader.upload(image, folder="zone-studio", resource_type="image")
    return jsonify(url=result["secure_url"], public_id=result["public_id"]), 201


initialize_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)

