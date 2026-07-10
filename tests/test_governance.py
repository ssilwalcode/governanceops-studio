import json
import tempfile
import unittest
from pathlib import Path

from governance import AssessmentInput, GovernanceEngine, ValidationError
from governance.storage import AssessmentStore


ROOT = Path(__file__).resolve().parents[1]


def payload(**overrides):
    value = {
        "name": "Hiring support assistant",
        "description": "An AI assistant summarizes resumes and recommends candidates to a trained recruiter for review.",
        "sector": "employment",
        "lifecycleStage": "design",
        "decisionImpact": "high",
        "autonomyLevel": "recommendation",
        "deploymentScale": "limited",
        "dataCategories": ["general personal"],
        "affectedGroups": ["job applicants"],
        "thirdPartyModel": False,
        "humanReview": True,
        "appealProcess": False,
        "monitoringPlan": False,
        "assessor": "Test assessor"
    }
    value.update(overrides)
    return value


class GovernanceEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = GovernanceEngine(ROOT / "data" / "governance_taxonomy.json")

    def test_high_impact_employment_use_escalates(self):
        result = self.engine.assess(AssessmentInput.from_dict(payload()))
        rule_ids = {risk["ruleId"] for risk in result["riskRegister"]}

        self.assertIn("employment-context", rule_ids)
        self.assertIn("consequential-decision", rule_ids)
        self.assertEqual(result["decision"]["outcome"], "escalate for governance review")

    def test_declared_control_reduces_residual_score(self):
        without_review = self.engine.assess(AssessmentInput.from_dict(payload(humanReview=False)))
        with_review = self.engine.assess(AssessmentInput.from_dict(payload(humanReview=True)))
        without = next(risk for risk in without_review["riskRegister"] if risk["ruleId"] == "consequential-decision")
        with_control = next(risk for risk in with_review["riskRegister"] if risk["ruleId"] == "consequential-decision")

        self.assertLess(with_control["residualScore"], without["residualScore"])
        self.assertIn("human review declared", with_control["creditedControls"])

    def test_monitoring_gap_is_lifecycle_sensitive(self):
        design = self.engine.assess(AssessmentInput.from_dict(payload(lifecycleStage="design", monitoringPlan=False)))
        pilot = self.engine.assess(AssessmentInput.from_dict(payload(lifecycleStage="pilot", monitoringPlan=False)))

        self.assertNotIn("missing-monitoring", {risk["ruleId"] for risk in design["riskRegister"]})
        self.assertIn("missing-monitoring", {risk["ruleId"] for risk in pilot["riskRegister"]})

    def test_nlp_does_not_treat_negated_automation_as_confirmed(self):
        signals = self.engine.extract_signals(
            "The assistant makes recommendations but cannot automatically reject a candidate or take autonomous action."
        )

        self.assertNotIn("automated decision", {signal["label"] for signal in signals})

    def test_nlp_surfaces_biometric_signal(self):
        signals = self.engine.extract_signals("The system uses facial recognition to verify identity before access is granted.")

        self.assertIn("biometric", {signal["label"] for signal in signals})

    def test_limited_assistant_does_not_trigger_public_deployment(self):
        result = self.engine.assess(AssessmentInput.from_dict(payload(deploymentScale="limited")))

        self.assertNotIn("public-deployment", {risk["ruleId"] for risk in result["riskRegister"]})

    def test_public_scale_triggers_transparency_risk(self):
        result = self.engine.assess(AssessmentInput.from_dict(payload(deploymentScale="public")))

        self.assertIn("public-deployment", {risk["ruleId"] for risk in result["riskRegister"]})

    def test_assessment_maps_controls_to_frameworks(self):
        result = self.engine.assess(AssessmentInput.from_dict(payload()))
        names = {framework["name"] for framework in result["frameworkMap"]}

        self.assertIn("NIST AI RMF", names)
        self.assertIn("UNESCO Ethics of AI", names)

    def test_validation_rejects_short_description(self):
        with self.assertRaises(ValidationError):
            AssessmentInput.from_dict(payload(description="Too short"))


class AssessmentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = AssessmentStore(Path(self.temp_dir.name) / "assessments.json")
        engine = GovernanceEngine(ROOT / "data" / "governance_taxonomy.json")
        self.assessment = engine.assess(AssessmentInput.from_dict(payload()))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_persists_initial_audit_event(self):
        saved = self.store.save(self.assessment)

        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(saved["auditTrail"][0]["event"], "assessment_created")

    def test_review_change_is_audited(self):
        saved = self.store.save(self.assessment)
        updated = self.store.update_review(saved["assessmentId"], {
            "status": "in_review",
            "reviewer": "Governance reviewer",
            "note": "Fairness evidence must be completed before approval."
        })

        self.assertEqual(updated["status"], "in_review")
        self.assertEqual(updated["auditTrail"][-1]["previousStatus"], "draft")

    def test_invalid_review_status_is_rejected(self):
        saved = self.store.save(self.assessment)
        with self.assertRaises(ValueError):
            self.store.update_review(saved["assessmentId"], {
                "status": "auto_approved",
                "reviewer": "Reviewer",
                "note": "This status must never be accepted."
            })

    def test_approval_is_blocked_without_verified_evidence(self):
        saved = self.store.save(self.assessment)

        with self.assertRaisesRegex(ValueError, "Approval blocked"):
            self.store.update_review(saved["assessmentId"], {
                "status": "approved_with_conditions",
                "reviewer": "Governance reviewer",
                "note": "Attempt approval before evidence is verified."
            })

    def test_accepted_evidence_unlocks_approval(self):
        saved = self.store.save(self.assessment)
        control_ids = [control["id"] for control in saved["controlPlan"]]
        with_evidence = self.store.add_evidence(saved["assessmentId"], {
            "title": "Complete governance evidence pack",
            "reference": "internal://governance/evidence-pack-v1",
            "owner": "AI governance",
            "submittedBy": "Evidence owner",
            "version": "1.0",
            "controlIds": control_ids
        })
        evidence_id = with_evidence["evidenceArtifacts"][0]["evidenceId"]
        reviewed = self.store.review_evidence(saved["assessmentId"], evidence_id, {
            "status": "accepted",
            "reviewer": "Independent reviewer",
            "note": "The evidence pack covers every required control for this screening."
        })
        approved = self.store.update_review(saved["assessmentId"], {
            "status": "approved_with_conditions",
            "reviewer": "Governance reviewer",
            "note": "Approval granted subject to the recorded operational conditions."
        })

        self.assertEqual(reviewed["evidenceCoverage"]["percent"], 100)
        self.assertEqual(approved["status"], "approved_with_conditions")

    def test_expired_evidence_does_not_count_toward_coverage(self):
        saved = self.store.save(self.assessment)
        control_ids = [control["id"] for control in saved["controlPlan"]]
        with_evidence = self.store.add_evidence(saved["assessmentId"], {
            "title": "Expired evidence pack",
            "reference": "internal://governance/expired-pack",
            "owner": "AI governance",
            "submittedBy": "Evidence owner",
            "version": "0.9",
            "expiresAt": "2000-01-01",
            "controlIds": control_ids
        })
        evidence_id = with_evidence["evidenceArtifacts"][0]["evidenceId"]
        reviewed = self.store.review_evidence(saved["assessmentId"], evidence_id, {
            "status": "accepted",
            "reviewer": "Independent reviewer",
            "note": "The artifact is authentic but its validity period has expired."
        })

        self.assertEqual(reviewed["evidenceArtifacts"][0]["effectiveStatus"], "expired")
        self.assertEqual(reviewed["evidenceCoverage"]["percent"], 0)

    def test_revision_records_lineage_and_changes(self):
        saved = self.store.save(self.assessment)
        engine = GovernanceEngine(ROOT / "data" / "governance_taxonomy.json")
        revised_assessment = engine.assess(AssessmentInput.from_dict(payload(
            lifecycleStage="production",
            monitoringPlan=True,
            appealProcess=True
        )))
        revision = self.store.create_revision(saved["assessmentId"], revised_assessment)
        previous = self.store.get(saved["assessmentId"])

        self.assertEqual(revision["revision"], 2)
        self.assertEqual(revision["rootAssessmentId"], saved["assessmentId"])
        self.assertEqual(revision["previousRevisionId"], saved["assessmentId"])
        self.assertEqual(previous["supersededBy"], revision["assessmentId"])
        self.assertIn("monitoring_plan", {change["field"] for change in revision["revisionChanges"]})

    def test_unchanged_revision_is_rejected(self):
        saved = self.store.save(self.assessment)
        engine = GovernanceEngine(ROOT / "data" / "governance_taxonomy.json")
        unchanged = engine.assess(AssessmentInput.from_dict(payload()))

        with self.assertRaisesRegex(ValueError, "No assessment changes detected"):
            self.store.create_revision(saved["assessmentId"], unchanged)

    def test_carried_evidence_requires_reverification(self):
        saved = self.store.save(self.assessment)
        control_ids = [control["id"] for control in saved["controlPlan"]]
        with_evidence = self.store.add_evidence(saved["assessmentId"], {
            "title": "Accepted control evidence",
            "reference": "internal://governance/accepted-pack",
            "owner": "AI governance",
            "submittedBy": "Evidence owner",
            "controlIds": control_ids
        })
        evidence_id = with_evidence["evidenceArtifacts"][0]["evidenceId"]
        self.store.review_evidence(saved["assessmentId"], evidence_id, {
            "status": "accepted",
            "reviewer": "Independent reviewer",
            "note": "Evidence accepted for the first assessment revision."
        })
        engine = GovernanceEngine(ROOT / "data" / "governance_taxonomy.json")
        revised = engine.assess(AssessmentInput.from_dict(payload(monitoringPlan=True)))
        revision = self.store.create_revision(saved["assessmentId"], revised)

        self.assertEqual(revision["evidenceArtifacts"][0]["effectiveStatus"], "submitted")
        self.assertFalse(revision["evidenceCoverage"]["approvalReady"])


if __name__ == "__main__":
    unittest.main()
