import copy
import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4


REVIEW_STATUSES = {"draft", "in_review", "approved_with_conditions", "rejected", "retired"}
EVIDENCE_REVIEW_STATUSES = {"accepted", "rejected"}


def _now():
    return datetime.now(timezone.utc).isoformat()


class AssessmentStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def list(self):
        with self._lock:
            records = [self._hydrate(item) for item in self._read()]
        return [
            {
                "assessmentId": item["assessmentId"],
                "rootAssessmentId": item["rootAssessmentId"],
                "revision": item["revision"],
                "name": item["input"]["name"],
                "sector": item["input"]["sector"],
                "riskLevel": item["riskLevel"],
                "status": item["status"],
                "generatedAt": item["generatedAt"],
                "decision": item["decision"],
                "evidenceCoverage": item["evidenceCoverage"],
                "supersededBy": item.get("supersededBy")
            }
            for item in sorted(records, key=lambda value: value["generatedAt"], reverse=True)
        ]

    def get(self, assessment_id):
        with self._lock:
            assessment = next((item for item in self._read() if item["assessmentId"] == assessment_id), None)
            return self._hydrate(assessment) if assessment else None

    def save(self, assessment):
        with self._lock:
            records = self._read()
            assessment["rootAssessmentId"] = assessment["assessmentId"]
            assessment["revision"] = 1
            assessment["previousRevisionId"] = None
            assessment["supersededBy"] = None
            assessment["revisionChanges"] = []
            assessment["evidenceArtifacts"] = []
            assessment["auditTrail"] = [{
                "event": "assessment_created",
                "status": "draft",
                "actor": assessment["input"]["assessor"],
                "note": "Initial screening assessment generated.",
                "at": _now()
            }]
            assessment = self._hydrate(assessment)
            records.append(assessment)
            self._write(records)
        return assessment

    def create_revision(self, assessment_id, revised_assessment):
        with self._lock:
            records = self._read()
            previous = next((item for item in records if item["assessmentId"] == assessment_id), None)
            if not previous:
                return None
            previous = self._hydrate(previous)
            if previous.get("supersededBy"):
                raise ValueError("Create the next revision from the latest assessment revision.")
            revised_assessment["rootAssessmentId"] = previous["rootAssessmentId"]
            revised_assessment["revision"] = previous["revision"] + 1
            revised_assessment["previousRevisionId"] = previous["assessmentId"]
            revised_assessment["supersededBy"] = None
            revised_assessment["evidenceArtifacts"] = copy.deepcopy(previous["evidenceArtifacts"])
            for artifact in revised_assessment["evidenceArtifacts"]:
                artifact["carriedFromRevision"] = previous["revision"]
                artifact["status"] = "submitted"
                artifact["verification"] = None
            revised_assessment["revisionChanges"] = self._revision_changes(previous, revised_assessment)
            if not revised_assessment["revisionChanges"]:
                raise ValueError("No assessment changes detected; a new revision was not created.")
            revised_assessment["auditTrail"] = [{
                "event": "assessment_revision_created",
                "status": "draft",
                "actor": revised_assessment["input"]["assessor"],
                "note": f"Revision {revised_assessment['revision']} created from {previous['assessmentId']}.",
                "at": _now()
            }]
            revised_assessment = self._hydrate(revised_assessment)
            previous_record = next(item for item in records if item["assessmentId"] == assessment_id)
            previous_record["supersededBy"] = revised_assessment["assessmentId"]
            records.append(revised_assessment)
            self._write(records)
        return revised_assessment

    def add_evidence(self, assessment_id, payload):
        with self._lock:
            records = self._read()
            assessment = next((item for item in records if item["assessmentId"] == assessment_id), None)
            if not assessment:
                return None
            assessment = self._hydrate(assessment)
            artifact = self._validate_evidence(payload, assessment)
            assessment["evidenceArtifacts"].append(artifact)
            assessment["auditTrail"].append({
                "event": "evidence_submitted",
                "status": assessment["status"],
                "actor": artifact["submittedBy"],
                "note": f"Evidence '{artifact['title']}' submitted for {len(artifact['controlIds'])} control(s).",
                "evidenceId": artifact["evidenceId"],
                "at": artifact["submittedAt"]
            })
            self._recalculate_evidence(assessment)
            self._replace(records, assessment)
            self._write(records)
        return assessment

    def review_evidence(self, assessment_id, evidence_id, payload):
        status = str(payload.get("status", "")).strip().lower()
        reviewer = str(payload.get("reviewer", "")).strip()
        note = str(payload.get("note", "")).strip()
        if status not in EVIDENCE_REVIEW_STATUSES:
            raise ValueError("Evidence status must be accepted or rejected.")
        self._validate_actor_note(reviewer, note, "reviewer", "evidence review note")

        with self._lock:
            records = self._read()
            assessment = next((item for item in records if item["assessmentId"] == assessment_id), None)
            if not assessment:
                return None
            assessment = self._hydrate(assessment)
            artifact = next((item for item in assessment["evidenceArtifacts"] if item["evidenceId"] == evidence_id), None)
            if not artifact:
                raise ValueError("Evidence artifact not found.")
            artifact["status"] = status
            artifact["verification"] = {"reviewer": reviewer, "note": note, "at": _now()}
            assessment["auditTrail"].append({
                "event": "evidence_reviewed",
                "status": assessment["status"],
                "actor": reviewer,
                "note": f"Evidence '{artifact['title']}' {status}: {note}",
                "evidenceId": evidence_id,
                "at": artifact["verification"]["at"]
            })
            self._recalculate_evidence(assessment)
            self._replace(records, assessment)
            self._write(records)
        return assessment

    def update_review(self, assessment_id, payload):
        status = str(payload.get("status", "")).strip().lower()
        reviewer = str(payload.get("reviewer", "")).strip()
        note = str(payload.get("note", "")).strip()
        if status not in REVIEW_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(REVIEW_STATUSES))}.")
        self._validate_actor_note(reviewer, note, "reviewer", "review note")

        with self._lock:
            records = self._read()
            assessment = next((item for item in records if item["assessmentId"] == assessment_id), None)
            if not assessment:
                return None
            assessment = self._hydrate(assessment)
            if assessment.get("supersededBy") and status == "approved_with_conditions":
                raise ValueError("A superseded revision cannot be approved.")
            if status == "approved_with_conditions" and assessment["evidenceCoverage"]["percent"] < 100:
                count = len(assessment["evidenceCoverage"]["blockedControlIds"])
                raise ValueError(f"Approval blocked: {count} required control(s) do not have accepted, current evidence.")
            previous_status = assessment["status"]
            assessment["status"] = status
            assessment["auditTrail"].append({
                "event": "review_status_changed",
                "previousStatus": previous_status,
                "status": status,
                "actor": reviewer,
                "note": note,
                "at": _now()
            })
            self._replace(records, assessment)
            self._write(records)
        return assessment

    def _hydrate(self, assessment):
        assessment.setdefault("rootAssessmentId", assessment["assessmentId"])
        assessment.setdefault("revision", 1)
        assessment.setdefault("previousRevisionId", None)
        assessment.setdefault("supersededBy", None)
        assessment.setdefault("revisionChanges", [])
        assessment.setdefault("evidenceArtifacts", [])
        assessment.setdefault("auditTrail", [])
        self._recalculate_evidence(assessment)
        return assessment

    def _recalculate_evidence(self, assessment):
        artifacts = assessment["evidenceArtifacts"]
        accepted_controls = set()
        submitted_controls = set()
        rejected_controls = set()
        for artifact in artifacts:
            effective_status = self._effective_status(artifact)
            artifact["effectiveStatus"] = effective_status
            target = {
                "accepted": accepted_controls,
                "submitted": submitted_controls,
                "rejected": rejected_controls
            }.get(effective_status)
            if target is not None:
                target.update(artifact["controlIds"])

        required_controls = [item["id"] for item in assessment.get("controlPlan", [])]
        for item in assessment.get("evidenceChecklist", []):
            control_id = item["controlId"]
            if control_id in accepted_controls:
                item["status"] = "verified"
            elif control_id in submitted_controls:
                item["status"] = "submitted for review"
            elif control_id in rejected_controls:
                item["status"] = "evidence rejected"
            elif item.get("status") == "verified":
                item["status"] = "required"

        blocked = [control_id for control_id in required_controls if control_id not in accepted_controls]
        total = len(required_controls)
        verified = total - len(blocked)
        assessment["evidenceCoverage"] = {
            "verifiedControlCount": verified,
            "requiredControlCount": total,
            "percent": round((verified / total) * 100) if total else 100,
            "blockedControlIds": blocked,
            "approvalReady": not blocked
        }

    def _validate_evidence(self, payload, assessment):
        title = str(payload.get("title", "")).strip()
        reference = str(payload.get("reference", "")).strip()
        owner = str(payload.get("owner", "")).strip()
        submitted_by = str(payload.get("submittedBy", "")).strip()
        version = str(payload.get("version", "")).strip() or "unspecified"
        effective_date = str(payload.get("effectiveDate", "")).strip() or None
        expires_at = str(payload.get("expiresAt", "")).strip() or None
        control_ids = payload.get("controlIds") or []
        if len(title) < 3 or len(title) > 180:
            raise ValueError("Evidence title must contain between 3 and 180 characters.")
        if len(reference) < 3 or len(reference) > 500:
            raise ValueError("Evidence reference must contain between 3 and 500 characters.")
        if len(owner) < 2 or len(owner) > 120 or len(submitted_by) < 2 or len(submitted_by) > 120:
            raise ValueError("Evidence owner and submitter must contain between 2 and 120 characters.")
        if not isinstance(control_ids, list) or not control_ids:
            raise ValueError("Select at least one control for the evidence artifact.")
        allowed_controls = {item["id"] for item in assessment.get("controlPlan", [])}
        invalid = set(control_ids) - allowed_controls
        if invalid:
            raise ValueError(f"Evidence references controls outside this assessment: {', '.join(sorted(invalid))}.")
        for label, value in (("effectiveDate", effective_date), ("expiresAt", expires_at)):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as error:
                    raise ValueError(f"{label} must use YYYY-MM-DD format.") from error
        return {
            "evidenceId": f"ev-{uuid4().hex[:12]}",
            "title": title,
            "reference": reference,
            "owner": owner,
            "version": version[:80],
            "effectiveDate": effective_date,
            "expiresAt": expires_at,
            "controlIds": list(dict.fromkeys(control_ids)),
            "status": "submitted",
            "submittedBy": submitted_by,
            "submittedAt": _now(),
            "verification": None,
            "carriedFromRevision": None
        }

    @staticmethod
    def _effective_status(artifact):
        if artifact.get("status") == "accepted" and artifact.get("expiresAt"):
            if date.fromisoformat(artifact["expiresAt"]) < date.today():
                return "expired"
        return artifact.get("status", "submitted")

    @staticmethod
    def _revision_changes(previous, revised):
        changes = []
        for field, new_value in revised["input"].items():
            old_value = previous["input"].get(field)
            if old_value != new_value:
                changes.append({"field": field, "before": old_value, "after": new_value})
        if previous["overallScore"] != revised["overallScore"]:
            changes.append({"field": "overallScore", "before": previous["overallScore"], "after": revised["overallScore"]})
        previous_rules = {item["ruleId"] for item in previous["riskRegister"]}
        revised_rules = {item["ruleId"] for item in revised["riskRegister"]}
        if previous_rules != revised_rules:
            changes.append({"field": "riskRules", "before": sorted(previous_rules), "after": sorted(revised_rules)})
        return changes

    @staticmethod
    def _validate_actor_note(actor, note, actor_label, note_label):
        if len(actor) < 2 or len(actor) > 120:
            raise ValueError(f"{actor_label} must contain between 2 and 120 characters.")
        if len(note) < 10 or len(note) > 2000:
            raise ValueError(f"{note_label} must contain between 10 and 2000 characters.")

    @staticmethod
    def _replace(records, assessment):
        index = next(index for index, item in enumerate(records) if item["assessmentId"] == assessment["assessmentId"])
        records[index] = assessment

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
