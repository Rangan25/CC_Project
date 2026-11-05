import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, send_from_directory, url_for
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv()

from aws_services.monitoring import configure_logging, get_aws_status
from aws_services.notifications import notify_incident_submitted, notify_incident_resolved
from aws_services.queue import enqueue_incident
from aws_services.storage import upload_image

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = INSTANCE_DIR / "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
CATEGORIES = ["Infrastructure", "Network", "Security", "Database", "Application", "Other"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Pending", "In Progress", "Resolved"]

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "local-development-key-change-me"),
    DATABASE=str(INSTANCE_DIR / "incidents.db"),
    UPLOAD_FOLDER=str(UPLOAD_DIR),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
)
INSTANCE_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
configure_logging()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute(
        """CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_name TEXT NOT NULL,
            reporter_email TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL,
            location TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            image_ref TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    db.commit()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def email_is_valid(value):
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value))


@app.template_filter("pretty_date")
def pretty_date(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%b %d, %Y · %I:%M %p")
    except (TypeError, ValueError):
        return value or "—"


@app.context_processor
def inject_globals():
    return {"current_year": datetime.now().year}


@app.route("/")
def dashboard():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM incidents WHERE status = 'Pending'").fetchone()[0]
    resolved = db.execute("SELECT COUNT(*) FROM incidents WHERE status = 'Resolved'").fetchone()[0]
    recent = db.execute("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 5").fetchall()
    return render_template(
        "dashboard.html", total=total, pending=pending, resolved=resolved,
        recent=recent, aws_status=get_aws_status(),
    )


@app.route("/incidents/new", methods=["GET", "POST"])
def new_incident():
    if request.method == "POST":
        fields = {
            "reporter_name": request.form.get("reporter_name", "").strip(),
            "reporter_email": request.form.get("reporter_email", "").strip(),
            "title": request.form.get("title", "").strip(),
            "description": request.form.get("description", "").strip(),
            "category": request.form.get("category", "").strip(),
            "priority": request.form.get("priority", "").strip(),
            "location": request.form.get("location", "").strip(),
        }
        if any(not value for value in fields.values()):
            flash("Please complete every required field.", "error")
        elif not email_is_valid(fields["reporter_email"]):
            flash("Enter a valid email address.", "error")
        elif fields["category"] not in CATEGORIES or fields["priority"] not in PRIORITIES:
            flash("Choose a valid incident category and priority.", "error")
        elif len(fields["description"]) > 5000 or len(fields["title"]) > 160:
            flash("The title or description is too long.", "error")
        else:
            image_ref = None
            image = request.files.get("image")
            if image and image.filename:
                if not allowed_file(image.filename):
                    flash("Upload a PNG, JPG, GIF, or WEBP image.", "error")
                    return render_template("new_incident.html", categories=CATEGORIES, priorities=PRIORITIES)
                safe_name = secure_filename(image.filename)
                image_ref = upload_image(image.stream, safe_name, app.config["UPLOAD_FOLDER"])

            created = now_iso()
            db = get_db()
            cursor = db.execute(
                """INSERT INTO incidents
                   (reporter_name, reporter_email, title, description, category, priority,
                    location, image_ref, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*fields.values(), image_ref, created, created),
            )
            incident_id = cursor.lastrowid
            db.commit()
            incident = dict(db.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone())
            queued = enqueue_incident(incident)
            if not queued:
                notify_incident_submitted(incident)
            app.logger.info("Incident %s submitted by %s", incident_id, fields["reporter_email"])
            flash("Incident submitted successfully.", "success")
            return redirect(url_for("incident_detail", incident_id=incident_id))

    return render_template("new_incident.html", categories=CATEGORIES, priorities=PRIORITIES)


@app.route("/incidents")
def incidents():
    query = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    if status not in STATUSES:
        status = ""
    sql = "SELECT * FROM incidents WHERE 1=1"
    params = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if query:
        term = f"%{query}%"
        sql += " AND (title LIKE ? OR description LIKE ? OR reporter_name LIKE ? OR location LIKE ?)"
        params.extend([term] * 4)
    sql += " ORDER BY CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, created_at DESC"
    rows = get_db().execute(sql, params).fetchall()
    return render_template("incidents.html", incidents=rows, query=query, selected_status=status, statuses=STATUSES)


@app.route("/incidents/<int:incident_id>", methods=["GET", "POST"])
def incident_detail(incident_id):
    db = get_db()
    row = db.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        new_status = request.form.get("status", "")
        if new_status not in STATUSES:
            flash("Choose a valid status.", "error")
        else:
            previous_status = row["status"]
            db.execute("UPDATE incidents SET status = ?, updated_at = ? WHERE id = ?", (new_status, now_iso(), incident_id))
            db.commit()
            updated = dict(db.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone())
            if new_status == "Resolved" and previous_status != "Resolved":
                notify_incident_resolved(updated)
            flash("Incident status updated.", "success")
            return redirect(url_for("incident_detail", incident_id=incident_id))
    return render_template("incident_detail.html", incident=row, statuses=STATUSES)


@app.route("/incidents/<int:incident_id>/image")
def incident_image(incident_id):
    row = get_db().execute("SELECT image_ref FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None or not row["image_ref"]:
        abort(404)
    image_ref = row["image_ref"]
    if image_ref.startswith("s3:"):
        from aws_services.storage import image_url
        target = image_url(image_ref[3:])
        if target:
            return redirect(target)
        abort(404)
    return send_from_directory(app.config["UPLOAD_FOLDER"], image_ref[6:])


@app.errorhandler(413)
def file_too_large(_error):
    flash("Image must be 8 MB or smaller.", "error")
    return redirect(request.referrer or url_for("new_incident"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
