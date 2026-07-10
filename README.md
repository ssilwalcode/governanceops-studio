# GovernanceOps Studio

GovernanceOps Studio is a local AI governance risk-assessment workspace. It converts an AI use-case description and declared control posture into an auditable screening assessment: risk register, control plan, evidence checklist, framework map, reviewer questions, evidence verification, revision lineage, and decision history.

The product is designed for AI specialists, model-risk teams, and governance reviewers who need a consistent starting point for human review. It does not make legal determinations or automatically approve AI systems.

## Core workflow

1. Record the AI system's intended purpose, lifecycle stage, autonomy, impact, data, affected groups, and deployment scale.
2. Extract transparent NLP signals from the free-text description and combine them with structured intake fields.
3. Evaluate data-driven governance rules and produce inherent and residual risk scores.
4. Credit declared controls while keeping their evidence status explicitly unverified.
5. Map required controls to governance themes from NIST AI RMF, the EU AI Act, UNESCO, and OECD.
6. Submit versioned evidence artifacts and link them to the controls they support.
7. Accept or reject evidence through an independent reviewer action; expired evidence does not count toward coverage.
8. Block approval until every required control has accepted, current evidence.
9. Create a new assessment revision when the system or control posture changes, preserving lineage and a field-level change summary.
10. Record a named human review decision with rationale in the assessment audit trail.
11. Export the complete assessment as JSON or a Markdown governance brief.

## Design principles

- **Human decision authority:** The engine can recommend escalation or conditions; only a reviewer can change the case status.
- **Explainable screening:** Every risk entry includes its triggering fields, inherent score, residual score, and credited controls.
- **Evidence over checkboxes:** A declared control lowers screening likelihood but remains unverified until an accepted, current artifact supports it.
- **Approval gates:** Approval is unavailable while required controls lack verified evidence or when a revision has been superseded.
- **Revision lineage:** Input or control changes create a new assessment revision rather than overwriting the previous screening record.
- **Bounded NLP:** The text analyzer uses visible lexical rules and clause-level negation. It surfaces signals for confirmation rather than pretending to understand policy context.
- **Framework separation:** Framework mappings provide governance orientation, not legal classification or compliance advice.
- **Local-first operation:** The app uses Python's standard library and stores assessments locally without sending case data to an external model or service.

## Architecture

```text
Browser assessment workspace
          |
          v
Python HTTP API and validation
          |
          +--> transparent NLP signal extraction
          +--> data-driven governance rules
          +--> control and framework mapping
          |
          v
Local assessment store
          +--> evidence artifacts and verification
          +--> immutable screening revisions
          +--> human review status
          +--> audit trail
          +--> JSON / Markdown export
```

The governance taxonomy lives in `data/governance_taxonomy.json`. It separates risk rules, controls, required evidence, owners, and framework themes so governance content can evolve without rewriting the assessment engine.

## Evidence lifecycle

Evidence artifacts are metadata records that point to a report, model card, test result, policy, or other controlled document. Each artifact records its owner, submitter, version, covered controls, effective date, optional expiration date, and reviewer decision.

```text
submitted -> accepted -> expired
         \-> rejected
```

Coverage is calculated at the control level. An artifact may cover several controls, but a control counts as verified only when at least one linked artifact is accepted and unexpired. The tool stores references rather than uploaded files so sensitive evidence can remain in an organization's existing document system.

## Assessment revisions

Saving a revision re-runs the assessment against the edited intake while preserving the root assessment ID, previous revision ID, risk changes, input changes, and carried evidence. Carried evidence returns to submitted status so a reviewer must confirm that it still applies. Superseded revisions remain available for audit but cannot be approved or used to create a competing revision branch, and unchanged input cannot create an empty revision.

## Risk model

Each triggered rule defines severity and likelihood on a five-point scale:

```text
inherent risk = severity x likelihood
residual risk = severity x likelihood after declared control credit
```

The highest residual rule score determines the overall screening level:

| Residual score | Screening level |
| ---: | --- |
| 20-25 | Critical |
| 12-19 | High |
| 6-11 | Moderate |
| 1-5 | Low |

These thresholds are portfolio demonstration defaults. A real organization should calibrate severity, likelihood, risk appetite, evidence requirements, and decision authority through its own governance process.

## Run locally

```bash
npm start
```

Open `http://127.0.0.1:5190`.

Run validation and tests:

```bash
npm run check
```

No package installation is required beyond Python 3 and Node.js for the JavaScript syntax check.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/meta` | Intake options and taxonomy metadata |
| `GET` | `/api/assessments` | Saved assessment summaries |
| `GET` | `/api/assessments/{id}` | Full assessment and audit trail |
| `POST` | `/api/assessments` | Validate, assess, and persist a use case |
| `POST` | `/api/assessments/{id}/revisions` | Create the next assessment revision |
| `POST` | `/api/assessments/{id}/evidence` | Submit an evidence artifact |
| `POST` | `/api/assessments/{id}/evidence/{evidenceId}/verify` | Accept or reject submitted evidence |
| `POST` | `/api/assessments/{id}/review` | Record a named human review decision |

Saved cases are written to `data/assessments.json`, which is ignored by Git because assessment content may be sensitive.

## Verification

The automated suite checks:

- High-impact employment risk detection
- Declared-control credit and residual scoring
- Lifecycle-sensitive monitoring requirements
- NLP signal extraction and negation handling
- Framework mapping
- Input validation
- Local persistence
- Review audit events
- Rejection of unsupported review states
- Evidence submission, acceptance, rejection, and expiration
- Approval blocking when evidence is incomplete
- Assessment revision lineage and change summaries

GitHub Actions runs the same `npm run check` quality gate on pushes to `main` and on pull requests.

## Boundaries

GovernanceOps Studio is a screening and documentation tool. It does not establish whether an AI system is lawful, safe, fair, or compliant. Its output depends on user-supplied facts, rule configuration, and unverified control declarations. A qualified multidisciplinary team should review the underlying system, evidence, affected populations, jurisdiction, and deployment context before making a decision.
