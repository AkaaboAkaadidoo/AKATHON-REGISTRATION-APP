import os
import re
import sqlite3
import io
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, send_file, abort
)
from werkzeug.security import generate_password_hash
import pandas as pd

# ---- Config ----
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(APP_DIR, "akathon.db")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "AKATHON_ADMIN_080828")  # use your actual key here
SECRET_KEY = os.environ.get("FLASK_SECRET", "dev_secret_key")
MAX_PER_COHORT = 30

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ---- DB helpers ----
def get_db_conn():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_conn()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        cohort INTEGER NOT NULL,
        mat TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()

init_db()

# ---- validation regex ----
USERNAME_RE = re.compile(r"^PLASU/(2024|2025)/FNAS/(\d{4})$")
PASSWORD_RE = re.compile(r"^AKTH/(2024|2025)/CCC/(\d{4})$")

# ---- helper to check admin key ----
def check_admin_key(key):
    return key and key == ADMIN_KEY

# ---- Routes ----

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/register", methods=["POST"])
def register():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    cohort = request.form.get("cohort", "").strip()

    if not username or not password or cohort not in ("2024", "2025"):
        flash("Please fill all fields and choose a cohort.", "danger")
        return redirect(url_for("index"))

    u_m = USERNAME_RE.match(username)
    p_m = PASSWORD_RE.match(password)

    if not u_m:
        flash("Username must be in the format PLASU/YEAR/FNAS/MAT (MAT = 4 digits).", "danger")
        return redirect(url_for("index"))
    if not p_m:
        flash("Password must be in the format AKTH/YEAR/CCC/MAT (MAT = 4 digits).", "danger")
        return redirect(url_for("index"))

    u_year, u_mat = u_m.group(1), u_m.group(2)
    p_year, p_mat = p_m.group(1), p_m.group(2)

    if u_year != cohort or p_year != cohort:
        flash("YEAR in username/password must match the chosen cohort.", "danger")
        return redirect(url_for("index"))
    if u_mat != p_mat:
        flash("MAT in username and password must be the same 4-digit number.", "danger")
        return redirect(url_for("index"))

    conn = get_db_conn()
    count = conn.execute("SELECT COUNT(*) as c FROM students WHERE cohort = ?", (cohort,)).fetchone()["c"]
    if count >= MAX_PER_COHORT:
        conn.close()
        flash(f"Registration for cohort {cohort} is full ({MAX_PER_COHORT} students).", "danger")
        return redirect(url_for("index"))

    if conn.execute("SELECT id FROM students WHERE username = ?", (username,)).fetchone() is not None:
        conn.close()
        flash("Username already registered.", "danger")
        return redirect(url_for("index"))

    password_hash = generate_password_hash(password)
    created_at = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO students (username, password_hash, cohort, mat, created_at) VALUES (?,?,?,?,?)",
        (username, password_hash, cohort, u_mat, created_at)
    )
    conn.commit()
    conn.close()

    flash("Registration successful — welcome to Akathon!", "success")
    return redirect(url_for("index"))

# ---- Admin Routes ----

@app.route("/admin")
def admin():
    key = request.args.get("key", "")
    if not check_admin_key(key):
        abort(403)  # Forbidden

    conn = get_db_conn()
    students = conn.execute(
        "SELECT id, username, cohort, mat, created_at FROM students ORDER BY cohort, created_at"
    ).fetchall()
    conn.close()
    return render_template("admin.html", students=students, admin_key=ADMIN_KEY)

@app.route("/delete/<int:student_id>")
def delete_student(student_id):
    key = request.args.get("key", "")
    if not check_admin_key(key):
        abort(403)
    conn = get_db_conn()
    conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()
    flash(f"Student {student_id} deleted successfully.", "success")
    return redirect(url_for("admin", key=key))

@app.route("/export")
def export():
    key = request.args.get("key", "")
    if not check_admin_key(key):
        abort(403)
    conn = get_db_conn()
    df = pd.read_sql_query("SELECT id, username, cohort, mat, created_at FROM students ORDER BY cohort, created_at", conn)
    conn.close()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="students")
    output.seek(0)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return send_file(output,
                     as_attachment=True,
                     download_name=f"akathon_students_{ts}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/download-db")
def download_db():
    key = request.args.get("key", "")
    if not check_admin_key(key):
        abort(403)
    return send_file(DATABASE, as_attachment=True)

@app.route("/debug-key")
def debug_key():
    return f"ADMIN_KEY in Flask = {ADMIN_KEY!r}"

@app.route("/health")
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
