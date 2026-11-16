import os
import secrets
from functools import wraps

import cloudinary
import cloudinary.uploader
import psycopg
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
CORS(app, origins=os.getenv("FRONTEND_ORIGIN", "*").split(","), allow_headers=["Content-Type", "Authorization"])
DATABASE_URL = os.environ["DATABASE_URL"]
cloudinary.config(cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"), api_key=os.getenv("CLOUDINARY_API_KEY"),
                  api_secret=os.getenv("CLOUDINARY_API_SECRET"), secure=True)


def db():
    return psycopg.connect(DATABASE_URL, sslmode="require", row_factory=psycopg.rows.dict_row)


def initialize_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'customer'")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT ''")
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS bookings (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, service TEXT NOT NULL,
            date DATE NOT NULL, time TEXT NOT NULL, location TEXT NOT NULL DEFAULT '', package TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '', payment_method TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_method TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE SET NULL")
        conn.execute("""CREATE TABLE IF NOT EXISTS studio_services (
            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'Photography', price TEXT NOT NULL DEFAULT '',
            active BOOLEAN NOT NULL DEFAULT true, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("ALTER TABLE studio_services ADD COLUMN IF NOT EXISTS website_key TEXT UNIQUE")
        conn.execute("""CREATE TABLE IF NOT EXISTS studio_contacts (
            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '', message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'New',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS studio_images (
            id BIGSERIAL PRIMARY KEY, url TEXT NOT NULL, public_id TEXT NOT NULL,
            file_name TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Event',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("ALTER TABLE studio_images ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'Event'")
        conn.execute("DELETE FROM users WHERE lower(email) IN ('admin@zonestudio.example','customer@zonestudio.example')")
        _create_initial_admin(conn)


def _create_initial_admin(conn):
    email = os.getenv("INITIAL_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    name = os.getenv("INITIAL_ADMIN_NAME", "Zone Studio Administrator").strip()
    if not email and not password and not os.getenv("INITIAL_ADMIN_NAME"):
        return
    if not email or "@" not in email or not password or len(password) < 14 or not name:
        raise RuntimeError("Set INITIAL_ADMIN_EMAIL, INITIAL_ADMIN_PASSWORD (at least 14 characters), and INITIAL_ADMIN_NAME together.")
    conn.execute("""INSERT INTO users(name,email,password_hash,role) VALUES (%s,%s,%s,'admin')
        ON CONFLICT(email) DO NOTHING""", (name, email, generate_password_hash(password)))


def _public_user(row):
    return {"id": row["id"], "name": row["name"], "email": row["email"], "phone": row.get("phone", ""),
            "role": row.get("role", "customer"), "createdAt": row["created_at"].isoformat() if row.get("created_at") else None}


def _booking(row):
    item = dict(row)
    item["id"] = f"BK-{item['id']}"
    item["date"] = str(item["date"])
    created = item.pop("created_at", None)
    item["createdAt"] = created.isoformat() if created else None
    return item


def _current_user():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return None
    with db() as conn:
        return conn.execute("""SELECT u.id,u.name,u.email,u.phone,u.role,u.created_at
            FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=%s""", (token,)).fetchone()


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        g.user = _current_user()
        if not g.user:
            return jsonify(error="Please sign in to continue."), 401
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            return jsonify(error="Administrator access is required."), 403
        return fn(*args, **kwargs)
    return wrapped


@app.get("/api/health")
def health():
    return jsonify(status="ok")


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    name, email, password = (str(data.get(k, "")).strip() for k in ("name", "email", "password"))
    if not name or "@" not in email or len(password) < 12:
        return jsonify(error="Enter your name, a valid email, and a password with at least 12 characters."), 400
    token = secrets.token_urlsafe(40)
    try:
        with db() as conn:
            user = conn.execute("""INSERT INTO users(name,email,password_hash,role,phone)
                VALUES (%s,%s,%s,'customer',%s) RETURNING id,name,email,phone,role,created_at""",
                (name, email.lower(), generate_password_hash(password), str(data.get("phone", "")).strip())).fetchone()
            conn.execute("INSERT INTO sessions(token,user_id) VALUES (%s,%s)", (token, user["id"]))
    except psycopg.errors.UniqueViolation:
        return jsonify(error="An account with this email already exists."), 409
    return jsonify(token=token, user=_public_user(user)), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], str(data.get("password", ""))):
            return jsonify(error="Email or password is incorrect."), 401
        token = secrets.token_urlsafe(40)
        conn.execute("INSERT INTO sessions(token,user_id) VALUES (%s,%s)", (token, user["id"]))
    return jsonify(token=token, user=_public_user(user))


@app.get("/api/auth/me")
@login_required
def auth_me():
    return jsonify(user=_public_user(g.user))


@app.post("/api/auth/logout")
@login_required
def logout():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token=%s", (token,))
    return jsonify(status="ok")


@app.patch("/api/profile")
@login_required
def update_profile():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    if not name:
        return jsonify(error="Your name is required."), 400
    with db() as conn:
        user = conn.execute("UPDATE users SET name=%s,phone=%s WHERE id=%s RETURNING id,name,email,phone,role,created_at",
                            (name, phone, g.user["id"])).fetchone()
    return jsonify(user=_public_user(user))


@app.get("/api/bookings")
@login_required
def list_bookings():
    with db() as conn:
        if g.user["role"] == "admin":
            rows = conn.execute("SELECT * FROM bookings ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM bookings WHERE user_id=%s OR (user_id IS NULL AND lower(email)=lower(%s)) ORDER BY created_at DESC",
                                (g.user["id"], g.user["email"])).fetchall()
    return jsonify(bookings=[_booking(row) for row in rows])


@app.post("/api/bookings")
def create_booking():
    data = request.get_json(silent=True) or {}
    required = ("name", "email", "phone", "service", "date", "time", "package")
    if any(not str(data.get(key, "")).strip() for key in required):
        return jsonify(error="Please complete all required booking fields."), 400
    user = _current_user()
    try:
        with db() as conn:
            row = conn.execute("""INSERT INTO bookings(user_id,name,email,phone,service,date,time,location,package,notes,payment_method)
                VALUES (%(user_id)s,%(name)s,%(email)s,%(phone)s,%(service)s,%(date)s,%(time)s,%(location)s,%(package)s,%(notes)s,%(payment_method)s)
                RETURNING *""", {**data, "user_id": user["id"] if user else None,
                "location": data.get("location", ""), "notes": data.get("notes", ""),
                "payment_method": data.get("payment_method", "")}).fetchone()
    except (psycopg.errors.InvalidDatetimeFormat, psycopg.errors.DateTimeFieldOverflow):
        return jsonify(error="Choose a valid booking date."), 400
    return jsonify(booking=_booking(row)), 201


@app.patch("/api/admin/bookings/<int:booking_id>")
@admin_required
def update_booking(booking_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip()
    if status not in {"Pending", "Confirmed", "Completed", "Cancelled"}:
        return jsonify(error="Choose a valid booking status."), 400
    with db() as conn:
        row = conn.execute("UPDATE bookings SET status=%s WHERE id=%s RETURNING *", (status, booking_id)).fetchone()
    if not row:
        return jsonify(error="Booking not found."), 404
    return jsonify(booking=_booking(row))


@app.get("/api/admin/users")
@admin_required
def admin_users():
    with db() as conn:
        rows = conn.execute("SELECT id,name,email,phone,role,created_at FROM users ORDER BY created_at DESC").fetchall()
    return jsonify(users=[_public_user(row) for row in rows])


@app.get("/api/services")
def list_services():
    with db() as conn:
        rows = conn.execute("SELECT id,website_key,name,description,category,price,active,updated_at FROM studio_services WHERE active=true ORDER BY id").fetchall()
    return jsonify(services=[{**dict(row), "id": str(row["id"]), "updatedAt": row["updated_at"].isoformat()} for row in rows])


@app.post("/api/admin/services/sync")
@admin_required
def sync_website_services():
    items = (request.get_json(silent=True) or {}).get("services", [])
    if not isinstance(items, list):
        return jsonify(error="Send a list of website services."), 400
    with db() as conn:
        for item in items:
            key = str(item.get("key", "")).strip()
            name = str(item.get("name", "")).strip()
            if key and name:
                conn.execute("""INSERT INTO studio_services(website_key,name,description,category,price)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT(website_key) DO NOTHING""",
                    (key, name, str(item.get("description", "")).strip(), str(item.get("category", "Photography")).strip(), str(item.get("price", "")).strip()))
    return jsonify(status="ok")


@app.post("/api/admin/services")
@admin_required
def create_service():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify(error="A service name is required."), 400
    with db() as conn:
        row = conn.execute("""INSERT INTO studio_services(name,description,category,price)
            VALUES (%s,%s,%s,%s) RETURNING *""", (name, str(data.get("description", "")).strip(),
            str(data.get("category", "Photography")).strip(), str(data.get("price", "")).strip())).fetchone()
    return jsonify(service={**dict(row), "id": str(row["id"]), "updatedAt": row["updated_at"].isoformat()}), 201


@app.patch("/api/admin/services/<int:service_id>")
@admin_required
def edit_service(service_id):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify(error="A service name is required."), 400
    with db() as conn:
        row = conn.execute("""UPDATE studio_services SET name=%s,description=%s,category=%s,price=%s,
            updated_at=now() WHERE id=%s AND active=true RETURNING *""", (name,
            str(data.get("description", "")).strip(), str(data.get("category", "Photography")).strip(),
            str(data.get("price", "")).strip(), service_id)).fetchone()
    if not row:
        return jsonify(error="Service not found."), 404
    return jsonify(service={**dict(row), "id": str(row["id"]), "updatedAt": row["updated_at"].isoformat()})


@app.delete("/api/admin/services/<int:service_id>")
@admin_required
def delete_service(service_id):
    with db() as conn:
        row = conn.execute("UPDATE studio_services SET active=false,updated_at=now() WHERE id=%s AND active=true RETURNING id", (service_id,)).fetchone()
    return (jsonify(status="ok"), 200) if row else (jsonify(error="Service not found."), 404)


@app.post("/api/contacts")
def create_contact():
    data = request.get_json(silent=True) or {}
    name, email, message = (str(data.get(k, "")).strip() for k in ("name", "email", "message"))
    if not name or "@" not in email or not message:
        return jsonify(error="Enter your name, a valid email, and a message."), 400
    with db() as conn:
        row = conn.execute("""INSERT INTO studio_contacts(name,email,phone,subject,message)
            VALUES (%s,%s,%s,%s,%s) RETURNING id""", (name, email.lower(), str(data.get("phone", "")).strip(),
            str(data.get("subject", "")).strip(), message)).fetchone()
    return jsonify(id=row["id"], status="received"), 201


@app.get("/api/admin/contacts")
@admin_required
def admin_contacts():
    with db() as conn:
        rows = conn.execute("SELECT * FROM studio_contacts ORDER BY created_at DESC").fetchall()
    return jsonify(contacts=[{**dict(row), "createdAt": row["created_at"].isoformat()} for row in rows])


@app.patch("/api/admin/contacts/<int:contact_id>")
@admin_required
def update_contact(contact_id):
    status = str((request.get_json(silent=True) or {}).get("status", "")).strip()
    if status not in {"New", "In progress", "Resolved"}:
        return jsonify(error="Choose a valid contact status."), 400
    with db() as conn:
        row = conn.execute("UPDATE studio_contacts SET status=%s WHERE id=%s RETURNING id,status", (status, contact_id)).fetchone()
    return (jsonify(contact=dict(row)), 200) if row else (jsonify(error="Contact not found."), 404)


@app.post("/api/images")
@admin_required
def upload_image():
    image = request.files.get("image")
    if not image:
        return jsonify(error="Choose an image to upload."), 400
    if image.mimetype not in {"image/jpeg", "image/png", "image/webp"}:
        return jsonify(error="Upload a JPEG, PNG, or WebP image."), 400
    category = str(request.form.get("category", "Event")).strip()
    if category not in {"Event", "Event Photography", "Birthday", "Outdoors", "Indoors Studio", "Family", "Couple", "Corporate"}:
        return jsonify(error="Choose a valid photo category."), 400
    if not os.getenv("CLOUDINARY_CLOUD_NAME") or not os.getenv("CLOUDINARY_API_KEY") or not os.getenv("CLOUDINARY_API_SECRET"):
        return jsonify(error="Photo uploads are not configured yet. Add the Cloudinary settings to the backend."), 503
    result = cloudinary.uploader.upload(image, folder="zone-studio", resource_type="image")
    with db() as conn:
        row = conn.execute("INSERT INTO studio_images(url,public_id,file_name,category) VALUES (%s,%s,%s,%s) RETURNING id,created_at,category",
                           (result["secure_url"], result["public_id"], image.filename or "Photo", category)).fetchone()
    return jsonify(id=row["id"], url=result["secure_url"], public_id=result["public_id"], category=row["category"], createdAt=row["created_at"].isoformat()), 201


@app.get("/api/images")
def public_images():
    with db() as conn:
        rows = conn.execute("SELECT id,url,file_name,category FROM studio_images ORDER BY created_at DESC").fetchall()
    return jsonify(images=[{**dict(row), "id": str(row["id"])} for row in rows])


@app.get("/api/admin/images")
@admin_required
def admin_images():
    with db() as conn:
        rows = conn.execute("SELECT id,url,public_id,file_name,category,created_at FROM studio_images ORDER BY created_at DESC").fetchall()
    return jsonify(images=[{**dict(row), "createdAt": row["created_at"].isoformat()} for row in rows])


initialize_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
