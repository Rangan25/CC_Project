import io
import tempfile
import unittest
from pathlib import Path

import app as app_module


class IncidentReporterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        app_module.app.config.update(
            TESTING=True,
            DATABASE=str(Path(self.temp_dir.name) / "test.db"),
            UPLOAD_FOLDER=str(Path(self.temp_dir.name) / "uploads"),
            WTF_CSRF_ENABLED=False,
        )
        with app_module.app.app_context():
            app_module.init_db()
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def sample_form(self, **overrides):
        form = {
            "reporter_name": "Test Reporter",
            "reporter_email": "reporter@example.com",
            "title": "Test database latency",
            "description": "Latency increased after the latest deploy.",
            "category": "Database",
            "priority": "High",
            "location": "us-east-1",
        }
        form.update(overrides)
        return form

    def test_dashboard_and_empty_incidents_load(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/incidents").status_code, 200)

    def test_submit_search_view_and_resolve_incident(self):
        response = self.client.post("/incidents/new", data=self.sample_form(), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Incident status", response.data)
        listing = self.client.get("/incidents?q=database&status=Pending")
        self.assertIn(b"Test database latency", listing.data)
        detail = self.client.post("/incidents/1", data={"status": "Resolved"}, follow_redirects=True)
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Resolved", detail.data)
        self.assertEqual(self.client.get("/incidents?status=Resolved").status_code, 200)

    def test_rejects_invalid_email(self):
        response = self.client.post("/incidents/new", data=self.sample_form(reporter_email="nope"), follow_redirects=True)
        self.assertIn(b"valid email address", response.data)
        self.assertEqual(self.client.get("/incidents").status_code, 200)

    def test_image_upload_uses_local_fallback(self):
        data = self.sample_form()
        data["image"] = (io.BytesIO(b"fake-image-data"), "screen.png", "image/png")
        response = self.client.post("/incidents/new", data=data, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        with app_module.app.app_context():
            record = app_module.get_db().execute("SELECT image_ref FROM incidents WHERE id = 1").fetchone()
        self.assertEqual(record["image_ref"], "local:screen.png")
        image_response = self.client.get("/incidents/1/image")
        self.assertEqual(image_response.status_code, 200)
        image_response.close()

    def test_unknown_incident_returns_404(self):
        self.assertEqual(self.client.get("/incidents/999").status_code, 404)


if __name__ == "__main__":
    unittest.main()
