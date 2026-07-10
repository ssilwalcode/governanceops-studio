import json
import threading
from datetime import datetime, timezone
from pathlib import Path


REVIEW_STATUSES = {"draft", "in_review", "approved_with_conditions", "rejected", "retired"}


class AssessmentStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def list(self):
        records = self._read()
        return [
            {
                "assessmentId": item["assessmentId"],
                "name": item["input"]["name"],
                "sector": item["input"]["sector"],
                "riskLevel": item["riskLevel"],
                "status": item["status"],
                "generatedAt": item["generatedAt"],
                "decision": item["decision"]
            }
            for item in sorted(records, key=lambda value: value["generatedAt"], reverse=True)
        ]

    def get(self, assessment_id):
        return next((item for item in self._read() if item["assessmentId"] == assessment_id), None)

    def save(self, assessment):
        with self._lock:
            records = self._read()
            assessment["auditTrail"] = [{
                "event": "assessment_created",
                "status": "draft",
                "actor": assessment["input"]["assessor"],
                "note": "Initial screening assessment generated.",
                "at": datetime.now(timezone.utc).isoformat()
            }]
            records.append(assessment)
            self._write(records)
        return assessment

    def update_review(self, assessment_id, payload):
        status = str(payload.get("status", "")).strip().lower()
        reviewer = str(payload.get("reviewer", "")).strip()
        note = str(payload.get("note", "")).strip()
        if status not in REVIEW_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(REVIEW_STATUSES))}.")
        if len(reviewer) < 2 or len(reviewer) > 120:
            raise ValueError("reviewer must contain between 2 and 120 characters.")
        if len(note) < 10 or len(note) > 2000:
            raise ValueError("review note must contain between 10 and 2000 characters.")

        with self._lock:
            records = self._read()
            assessment = next((item for item in records if item["assessmentId"] == assessment_id), None)
            if not assessment:
                return None
            previous_status = assessment["status"]
            assessment["status"] = status
            assessment.setdefault("auditTrail", []).append({
                "event": "review_status_changed",
                "previousStatus": previous_status,
                "status": status,
                "actor": reviewer,
                "note": note,
                "at": datetime.now(timezone.utc).isoformat()
            })
            self._write(records)
        return assessment

    def _read(self):
        if not self.path.exists():
            return []
        value = json.loads(self.path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []

    def _write(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
