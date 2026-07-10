import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from governance import AssessmentInput, GovernanceEngine, ValidationError
from governance.storage import AssessmentStore


ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5190"))
ENGINE = GovernanceEngine(ROOT / "data" / "governance_taxonomy.json")
ASSESSMENTS_PATH = Path(os.environ.get("ASSESSMENTS_PATH", ROOT / "data" / "assessments.json"))
STORE = AssessmentStore(ASSESSMENTS_PATH)


class GovernanceHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("content-length", "0"))
        if length > 100_000:
            raise ValueError("Request body is too large.")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        value = json.loads(raw or "{}")
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def serve_static(self):
        pathname = unquote(urlparse(self.path).path)
        requested = "/index.html" if pathname == "/" else pathname
        file_path = (ROOT / requested.lstrip("/")).resolve()
        try:
            relative = file_path.relative_to(ROOT)
        except ValueError:
            self.send_error(403)
            return
        if relative.parts and relative.parts[0] == "data":
            self.send_error(403)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404)
            return
        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if file_path.suffix in {".html", ".css", ".js", ".md"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        pathname = urlparse(self.path).path
        if pathname == "/api/meta":
            self.send_json(200, ENGINE.metadata())
            return
        if pathname == "/api/assessments":
            self.send_json(200, {"assessments": STORE.list()})
            return
        if pathname.startswith("/api/assessments/"):
            assessment_id = pathname.rsplit("/", 1)[-1]
            assessment = STORE.get(assessment_id)
            self.send_json(200, assessment) if assessment else self.send_json(404, {"error": "Assessment not found."})
            return
        self.serve_static()

    def do_POST(self):
        pathname = urlparse(self.path).path
        parts = [part for part in pathname.split("/") if part]
        try:
            if pathname == "/api/assessments":
                assessment_input = AssessmentInput.from_dict(self.read_json())
                assessment = STORE.save(ENGINE.assess(assessment_input))
                self.send_json(201, assessment)
                return
            if len(parts) == 4 and parts[:2] == ["api", "assessments"] and parts[3] == "revisions":
                assessment_input = AssessmentInput.from_dict(self.read_json())
                revision = STORE.create_revision(parts[2], ENGINE.assess(assessment_input))
                self.send_json(201, revision) if revision else self.send_json(404, {"error": "Assessment not found."})
                return
            if len(parts) == 4 and parts[:2] == ["api", "assessments"] and parts[3] == "evidence":
                assessment = STORE.add_evidence(parts[2], self.read_json())
                self.send_json(201, assessment) if assessment else self.send_json(404, {"error": "Assessment not found."})
                return
            if (
                len(parts) == 6
                and parts[:2] == ["api", "assessments"]
                and parts[3] == "evidence"
                and parts[5] == "verify"
            ):
                assessment = STORE.review_evidence(parts[2], parts[4], self.read_json())
                self.send_json(200, assessment) if assessment else self.send_json(404, {"error": "Assessment not found."})
                return
            if pathname.startswith("/api/assessments/") and pathname.endswith("/review"):
                assessment_id = pathname.split("/")[-2]
                assessment = STORE.update_review(assessment_id, self.read_json())
                self.send_json(200, assessment) if assessment else self.send_json(404, {"error": "Assessment not found."})
                return
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
            return
        except Exception as error:
            self.send_json(500, {"error": str(error)})
            return
        self.send_json(404, {"error": "API route not found."})


def main():
    server = ThreadingHTTPServer((HOST, PORT), GovernanceHandler)
    print(f"GovernanceOps Studio running at http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
