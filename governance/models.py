from dataclasses import asdict, dataclass, field


SECTORS = {"employment", "education", "healthcare", "finance", "public services", "consumer", "general"}
LIFECYCLE_STAGES = {"design", "pilot", "pre-deployment", "production"}
DECISION_IMPACTS = {"low", "moderate", "high"}
AUTONOMY_LEVELS = {"assistive", "recommendation", "automated"}
DEPLOYMENT_SCALES = {"internal", "limited", "organization-wide", "public"}
DATA_CATEGORIES = {"none", "general personal", "sensitive personal", "biometric", "health", "financial"}
AFFECTED_GROUPS = {"employees", "job applicants", "students", "patients", "customers", "children", "general public"}


class ValidationError(ValueError):
    pass


def _choice(payload, key, allowed, default=None):
    value = str(payload.get(key, default or "")).strip().lower()
    if value not in allowed:
        raise ValidationError(f"{key} must be one of: {', '.join(sorted(allowed))}.")
    return value


def _list_choice(payload, key, allowed):
    raw = payload.get(key) or []
    if not isinstance(raw, list):
        raise ValidationError(f"{key} must be a list.")
    values = []
    for item in raw:
        value = str(item).strip().lower()
        if value not in allowed:
            raise ValidationError(f"Unsupported {key} value: {value}.")
        if value not in values:
            values.append(value)
    return values


def _boolean(payload, key, default=False):
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ValidationError(f"{key} must be true or false.")
    return value


@dataclass(frozen=True)
class AssessmentInput:
    name: str
    description: str
    sector: str
    lifecycle_stage: str
    decision_impact: str
    autonomy_level: str
    deployment_scale: str
    data_categories: list[str] = field(default_factory=list)
    affected_groups: list[str] = field(default_factory=list)
    third_party_model: bool = False
    human_review: bool = False
    appeal_process: bool = False
    monitoring_plan: bool = False
    assessor: str = "Portfolio reviewer"

    @classmethod
    def from_dict(cls, payload):
        name = str(payload.get("name", "")).strip()
        description = str(payload.get("description", "")).strip()
        assessor = str(payload.get("assessor", "Portfolio reviewer")).strip() or "Portfolio reviewer"
        if len(name) < 3 or len(name) > 120:
            raise ValidationError("name must contain between 3 and 120 characters.")
        if len(description) < 40 or len(description) > 5000:
            raise ValidationError("description must contain between 40 and 5000 characters.")
        return cls(
            name=name,
            description=description,
            sector=_choice(payload, "sector", SECTORS, "general"),
            lifecycle_stage=_choice(payload, "lifecycleStage", LIFECYCLE_STAGES, "design"),
            decision_impact=_choice(payload, "decisionImpact", DECISION_IMPACTS, "moderate"),
            autonomy_level=_choice(payload, "autonomyLevel", AUTONOMY_LEVELS, "assistive"),
            deployment_scale=_choice(payload, "deploymentScale", DEPLOYMENT_SCALES, "limited"),
            data_categories=_list_choice(payload, "dataCategories", DATA_CATEGORIES),
            affected_groups=_list_choice(payload, "affectedGroups", AFFECTED_GROUPS),
            third_party_model=_boolean(payload, "thirdPartyModel"),
            human_review=_boolean(payload, "humanReview"),
            appeal_process=_boolean(payload, "appealProcess"),
            monitoring_plan=_boolean(payload, "monitoringPlan"),
            assessor=assessor[:120]
        )

    def to_dict(self):
        return asdict(self)
