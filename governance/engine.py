import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import AssessmentInput


NEGATION_PATTERN = re.compile(r"\b(?:no|not|never|without|doesn't|does not|cannot|can't)\b[^.!?;]{0,80}$", re.IGNORECASE)


class GovernanceEngine:
    def __init__(self, taxonomy_path):
        self.taxonomy_path = Path(taxonomy_path)
        self.taxonomy = json.loads(self.taxonomy_path.read_text(encoding="utf-8"))
        self.controls = {control["id"]: control for control in self.taxonomy["controls"]}
        self.frameworks = {framework["id"]: framework for framework in self.taxonomy["frameworks"]}

    def metadata(self):
        return {
            "sectors": ["employment", "education", "healthcare", "finance", "public services", "consumer", "general"],
            "lifecycleStages": ["design", "pilot", "pre-deployment", "production"],
            "decisionImpacts": ["low", "moderate", "high"],
            "autonomyLevels": ["assistive", "recommendation", "automated"],
            "deploymentScales": ["internal", "limited", "organization-wide", "public"],
            "dataCategories": ["general personal", "sensitive personal", "biometric", "health", "financial"],
            "affectedGroups": ["employees", "job applicants", "students", "patients", "customers", "children", "general public"],
            "frameworks": list(self.frameworks.values()),
            "riskRuleCount": len(self.taxonomy["riskRules"]),
            "controlCount": len(self.controls)
        }

    def assess(self, assessment_input):
        signals = self.extract_signals(assessment_input.description)
        triggered = []
        for rule in self.taxonomy["riskRules"]:
            reasons = self._trigger_reasons(rule["trigger"], assessment_input, signals)
            if reasons:
                triggered.append((rule, reasons))

        risks = [self._risk_entry(rule, reasons, assessment_input) for rule, reasons in triggered]
        risks.sort(key=lambda item: item["residualScore"], reverse=True)
        required_control_ids = []
        for risk in risks:
            for control_id in risk["controlIds"]:
                if control_id not in required_control_ids:
                    required_control_ids.append(control_id)

        evidence = self._evidence_checklist(required_control_ids, assessment_input)
        framework_map = self._framework_map(required_control_ids, risks)
        overall_score = max((risk["residualScore"] for risk in risks), default=1)
        risk_level = self._risk_level(overall_score)
        decision = self._decision(risk_level, evidence, assessment_input)

        return {
            "assessmentId": f"gov-{uuid4().hex[:12]}",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "status": "draft",
            "input": assessment_input.to_dict(),
            "overallScore": overall_score,
            "riskLevel": risk_level,
            "decision": decision,
            "summary": self._summary(assessment_input, risk_level, risks, evidence),
            "signals": signals,
            "riskRegister": risks,
            "controlPlan": [self.controls[control_id] for control_id in required_control_ids],
            "evidenceChecklist": evidence,
            "frameworkMap": framework_map,
            "reviewQuestions": [risk["reviewQuestion"] for risk in risks[:8]],
            "scoringTrace": [
                {"ruleId": risk["ruleId"], "triggeredBy": risk["triggeredBy"], "inherentScore": risk["inherentScore"], "residualScore": risk["residualScore"]}
                for risk in risks
            ],
            "limitations": [
                "This is a screening assessment, not a legal classification or approval.",
                "Rule-based NLP signals require confirmation by a qualified reviewer.",
                "Residual scores reflect declared controls, not independently verified implementation."
            ]
        }

    def extract_signals(self, description):
        text = description.lower()
        signals = []
        vocabulary = {
            "employment": ["hiring", "recruitment", "resume", "candidate", "employee"],
            "education": ["student", "school", "grading", "admission"],
            "health": ["patient", "clinical", "diagnosis", "treatment", "health"],
            "biometric": ["biometric", "facial recognition", "face recognition", "fingerprint", "voiceprint"],
            "financial": ["credit", "loan", "insurance", "financial eligibility"],
            "public interaction": ["public-facing", "citizen-facing", "customer-facing"],
            "automated decision": ["automatically reject", "automatic decision", "without human review", "autonomous"]
        }
        for label, phrases in vocabulary.items():
            matches = [phrase for phrase in phrases if self._affirmed_phrase(text, phrase)]
            if matches:
                signals.append({"label": label, "matchedTerms": matches, "method": "transparent lexical rule"})
        return signals

    @staticmethod
    def _affirmed_phrase(text, phrase):
        start = text.find(phrase)
        while start >= 0:
            prefix = text[max(0, start - 90):start]
            if not NEGATION_PATTERN.search(prefix):
                return True
            start = text.find(phrase, start + len(phrase))
        return False

    def _trigger_reasons(self, trigger, data, signals):
        reasons = []
        checks = []
        values = {
            "sectors": data.sector,
            "decisionImpacts": data.decision_impact,
            "autonomyLevels": data.autonomy_level,
            "deploymentScales": data.deployment_scale,
            "lifecycleStages": data.lifecycle_stage
        }
        for key, current in values.items():
            expected = trigger.get(key, [])
            if expected:
                matched = current in expected
                checks.append(matched)
                if matched:
                    reasons.append(f"{key}: {current}")
        for key, current_values in (("dataCategories", data.data_categories), ("affectedGroups", data.affected_groups)):
            expected = trigger.get(key, [])
            if expected:
                matches = sorted(set(current_values).intersection(expected))
                checks.append(bool(matches))
                if matches:
                    reasons.append(f"{key}: {', '.join(matches)}")
        boolean_fields = trigger.get("booleans", [])
        if boolean_fields:
            matches = [attribute for attribute in boolean_fields if getattr(data, attribute)]
            checks.append(bool(matches))
            reasons.extend(f"{attribute}: confirmed" for attribute in matches)
        missing_fields = trigger.get("missingBooleans", [])
        if missing_fields:
            matches = [attribute for attribute in missing_fields if not getattr(data, attribute)]
            checks.append(bool(matches))
            reasons.extend(f"{attribute}: not confirmed" for attribute in matches)
        keywords = trigger.get("keywords", [])
        if keywords:
            keyword_matches = [keyword for keyword in keywords if self._affirmed_phrase(data.description.lower(), keyword)]
            checks.append(bool(keyword_matches))
            if keyword_matches:
                reasons.append(f"description signals: {', '.join(keyword_matches)}")
        if trigger.get("match") == "all" and not all(checks):
            return []
        return reasons

    def _risk_entry(self, rule, reasons, data):
        inherent_score = rule["severity"] * rule["likelihood"]
        residual_likelihood = rule["likelihood"]
        credited_controls = []
        if data.monitoring_plan and "monitoring" in rule["controlIds"]:
            residual_likelihood -= 1
            credited_controls.append("monitoring plan declared")
        if data.human_review and "human-oversight" in rule["controlIds"]:
            residual_likelihood -= 1
            credited_controls.append("human review declared")
        if data.appeal_process and "appeal-remedy" in rule["controlIds"]:
            residual_likelihood -= 1
            credited_controls.append("appeal process declared")
        residual_likelihood = max(1, residual_likelihood)
        return {
            "ruleId": rule["id"],
            "domain": rule["domain"],
            "title": rule["title"],
            "description": rule["description"],
            "severity": rule["severity"],
            "likelihood": rule["likelihood"],
            "inherentScore": inherent_score,
            "residualLikelihood": residual_likelihood,
            "residualScore": rule["severity"] * residual_likelihood,
            "rating": self._risk_level(rule["severity"] * residual_likelihood),
            "triggeredBy": reasons,
            "creditedControls": credited_controls,
            "controlIds": rule["controlIds"],
            "reviewQuestion": rule["question"]
        }

    def _evidence_checklist(self, control_ids, data):
        declared = {
            "human-oversight": data.human_review,
            "appeal-remedy": data.appeal_process,
            "monitoring": data.monitoring_plan
        }
        return [
            {
                "controlId": control_id,
                "artifact": self.controls[control_id]["evidence"],
                "owner": self.controls[control_id]["owner"],
                "status": "declared, verify evidence" if declared.get(control_id) else "required"
            }
            for control_id in control_ids
        ]

    def _framework_map(self, control_ids, risks):
        mapped_controls = defaultdict(list)
        for control_id in control_ids:
            for framework_id in self.controls[control_id]["frameworkIds"]:
                mapped_controls[framework_id].append(control_id)
        domains = sorted({risk["domain"] for risk in risks})
        return [
            {
                **self.frameworks[framework_id],
                "controlIds": ids,
                "riskDomains": domains
            }
            for framework_id, ids in mapped_controls.items()
        ]

    @staticmethod
    def _risk_level(score):
        if score >= 20:
            return "critical"
        if score >= 12:
            return "high"
        if score >= 6:
            return "moderate"
        return "low"

    @staticmethod
    def _decision(risk_level, evidence, data):
        required_count = sum(item["status"] == "required" for item in evidence)
        if risk_level in {"critical", "high"}:
            return {"outcome": "escalate for governance review", "reason": f"High-impact risks remain and {required_count} evidence artifacts require review."}
        if required_count or data.lifecycle_stage in {"pilot", "pre-deployment", "production"}:
            return {"outcome": "proceed with conditions", "reason": f"Complete and verify {required_count} required evidence artifacts before the next decision gate."}
        return {"outcome": "standard review", "reason": "No high residual risk was identified from the supplied information."}

    @staticmethod
    def _summary(data, risk_level, risks, evidence):
        domains = ", ".join(sorted({risk["domain"] for risk in risks[:5]})) or "no triggered domains"
        required_count = sum(item["status"] == "required" for item in evidence)
        return (
            f"{data.name} is screened as {risk_level} risk. The leading domains are {domains}. "
            f"The assessment identified {len(risks)} risk conditions and {required_count} evidence artifacts that are not yet declared."
        )
