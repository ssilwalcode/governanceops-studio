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


if __name__ == "__main__":
    unittest.main()
