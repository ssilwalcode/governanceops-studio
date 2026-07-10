let metadata = null;
let currentAssessment = null;

const elements = {
  form: document.getElementById("assessmentForm"),
  reviewForm: document.getElementById("reviewForm"),
  formError: document.getElementById("formError"),
  reviewError: document.getElementById("reviewError"),
  runButton: document.getElementById("runAssessmentButton"),
  newButton: document.getElementById("newAssessmentButton"),
  list: document.getElementById("assessmentList"),
  count: document.getElementById("assessmentCount"),
  pageTitle: document.getElementById("pageTitle"),
  saveStatus: document.getElementById("saveStatus"),
  emptyState: document.getElementById("emptyState"),
  output: document.getElementById("assessmentOutput"),
  decisionOutcome: document.getElementById("decisionOutcome"),
  summary: document.getElementById("assessmentSummary"),
  riskScore: document.getElementById("riskScore"),
  riskLevel: document.getElementById("riskLevel"),
  riskScoreBox: document.querySelector(".risk-score"),
  riskCount: document.getElementById("riskCount"),
  evidenceCount: document.getElementById("evidenceCount"),
  signalCount: document.getElementById("signalCount"),
  signalList: document.getElementById("signalList"),
  riskTableBody: document.getElementById("riskTableBody"),
  controlList: document.getElementById("controlList"),
  frameworkList: document.getElementById("frameworkList"),
  questionList: document.getElementById("questionList"),
  auditTrail: document.getElementById("auditTrail"),
  exportJson: document.getElementById("exportJsonButton"),
  exportBrief: document.getElementById("exportBriefButton")
};

function makeElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "content-type": "application/json" },
    ...options
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || "Request failed.");
  return body;
}

function titleCase(value) {
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function populateSelect(selectId, values, selected) {
  const select = document.getElementById(selectId);
  select.replaceChildren(...values.map((value) => new Option(titleCase(value), value, false, value === selected)));
}

function populateChecks(containerId, name, values, selectedValues = []) {
  const container = document.getElementById(containerId);
  const nodes = values.map((value) => {
    const label = makeElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = name;
    input.value = value;
    input.checked = selectedValues.includes(value);
    label.append(input, makeElement("span", "", titleCase(value)));
    return label;
  });
  container.replaceChildren(...nodes);
}

function initializeForm(meta) {
  populateSelect("sectorSelect", meta.sectors, "employment");
  populateSelect("lifecycleSelect", meta.lifecycleStages, "design");
  populateSelect("impactSelect", meta.decisionImpacts, "high");
  populateSelect("autonomySelect", meta.autonomyLevels, "recommendation");
  populateSelect("scaleSelect", meta.deploymentScales, "limited");
  populateChecks("dataCategories", "dataCategories", meta.dataCategories, ["general personal"]);
  populateChecks("affectedGroups", "affectedGroups", meta.affectedGroups, ["job applicants"]);
}

function checkedValues(name) {
  return [...elements.form.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value);
}

function assessmentPayload() {
  const formData = new FormData(elements.form);
  return {
    name: String(formData.get("name") || ""),
    assessor: String(formData.get("assessor") || ""),
    description: String(formData.get("description") || ""),
    sector: String(formData.get("sector") || "general"),
    lifecycleStage: String(formData.get("lifecycleStage") || "design"),
    decisionImpact: String(formData.get("decisionImpact") || "moderate"),
    autonomyLevel: String(formData.get("autonomyLevel") || "assistive"),
    deploymentScale: String(formData.get("deploymentScale") || "limited"),
    dataCategories: checkedValues("dataCategories"),
    affectedGroups: checkedValues("affectedGroups"),
    thirdPartyModel: Boolean(formData.get("thirdPartyModel")),
    humanReview: Boolean(formData.get("humanReview")),
    appealProcess: Boolean(formData.get("appealProcess")),
    monitoringPlan: Boolean(formData.get("monitoringPlan"))
  };
}

function fillForm(input) {
  const mapping = {
    name: input.name,
    assessor: input.assessor,
    description: input.description,
    sector: input.sector,
    lifecycleStage: input.lifecycle_stage,
    decisionImpact: input.decision_impact,
    autonomyLevel: input.autonomy_level,
    deploymentScale: input.deployment_scale
  };
  Object.entries(mapping).forEach(([name, value]) => {
    const field = elements.form.elements.namedItem(name);
    if (field) field.value = value;
  });
  ["dataCategories", "affectedGroups"].forEach((name) => {
    const selected = input[name === "dataCategories" ? "data_categories" : "affected_groups"] || [];
    elements.form.querySelectorAll(`input[name="${name}"]`).forEach((box) => {
      box.checked = selected.includes(box.value);
    });
  });
  const booleans = {
    thirdPartyModel: input.third_party_model,
    humanReview: input.human_review,
    appealProcess: input.appeal_process,
    monitoringPlan: input.monitoring_plan
  };
  Object.entries(booleans).forEach(([name, value]) => {
    elements.form.elements.namedItem(name).checked = Boolean(value);
  });
}

function renderSignals(signals) {
  elements.signalList.replaceChildren(...signals.map((signal) => {
    const terms = signal.matchedTerms.join(", ");
    return makeElement("span", "", `${signal.label}: ${terms}`);
  }));
}

function tableCell(primary, secondary, className = "") {
  const cell = makeElement("td", className);
  cell.append(makeElement("strong", "", primary));
  if (secondary) cell.append(makeElement("small", "", secondary));
  return cell;
}

function renderRiskRegister(risks) {
  const rows = risks.map((risk) => {
    const row = document.createElement("tr");
    row.append(
      tableCell(risk.title, risk.description),
      tableCell(titleCase(risk.domain), ""),
      tableCell(String(risk.inherentScore), `${risk.severity} severity x ${risk.likelihood} likelihood`),
      tableCell(String(risk.residualScore), `${risk.rating} risk`, `rating ${risk.rating}`),
      tableCell(risk.triggeredBy.join("; "), risk.creditedControls.join("; ") || "No declared control credit")
    );
    return row;
  });
  elements.riskTableBody.replaceChildren(...rows);
}

function renderControls(controls, evidence) {
  const evidenceByControl = Object.fromEntries(evidence.map((item) => [item.controlId, item]));
  const cards = controls.map((control) => {
    const item = evidenceByControl[control.id];
    const article = makeElement("article", "control-item");
    const header = document.createElement("header");
    const heading = document.createElement("div");
    heading.append(makeElement("h3", "", control.name), makeElement("p", "", `${control.owner} | ${item.artifact}`));
    const statusClass = item.status.startsWith("declared") ? "evidence-status declared" : "evidence-status";
    header.append(heading, makeElement("span", statusClass, item.status));
    const tags = makeElement("div", "framework-tags");
    control.frameworkIds.forEach((id) => tags.append(makeElement("span", "", id)));
    article.append(header, tags);
    return article;
  });
  elements.controlList.replaceChildren(...cards);
}

function renderFrameworks(frameworks) {
  const cards = frameworks.map((framework) => {
    const article = makeElement("article", "framework-item");
    const header = document.createElement("header");
    const heading = document.createElement("div");
    heading.append(makeElement("h3", "", `${framework.name} / ${framework.theme}`), makeElement("p", "", framework.description));
    header.append(heading, makeElement("span", "evidence-status declared", `${framework.controlIds.length} controls`));
    const tags = makeElement("div", "framework-tags");
    framework.riskDomains.forEach((domain) => tags.append(makeElement("span", "", domain)));
    article.append(header, tags);
    return article;
  });
  elements.frameworkList.replaceChildren(...cards);
}

function renderQuestions(questions) {
  elements.questionList.replaceChildren(...questions.map((question) => makeElement("li", "", question)));
}

function formatTime(value) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function renderAuditTrail(events = []) {
  const cards = [...events].reverse().map((event) => {
    const article = makeElement("article", "audit-event");
    const header = document.createElement("header");
    header.append(makeElement("strong", "", titleCase(event.event)), makeElement("small", "", formatTime(event.at)));
    article.append(header, makeElement("small", "", `${event.actor} | ${titleCase(event.status)}`), makeElement("p", "", event.note));
    return article;
  });
  elements.auditTrail.replaceChildren(...cards);
}

function renderAssessment(assessment) {
  currentAssessment = assessment;
  elements.emptyState.hidden = true;
  elements.output.hidden = false;
  elements.pageTitle.textContent = assessment.input.name;
  elements.saveStatus.textContent = `${titleCase(assessment.status)} | ${formatTime(assessment.generatedAt)}`;
  elements.decisionOutcome.textContent = assessment.decision.outcome;
  elements.summary.textContent = assessment.summary;
  elements.riskScore.textContent = assessment.overallScore;
  elements.riskLevel.textContent = assessment.riskLevel;
  elements.riskScoreBox.className = `risk-score ${assessment.riskLevel}`;
  elements.riskCount.textContent = assessment.riskRegister.length;
  elements.evidenceCount.textContent = assessment.evidenceChecklist.length;
  elements.signalCount.textContent = assessment.signals.length;
  renderSignals(assessment.signals);
  renderRiskRegister(assessment.riskRegister);
  renderControls(assessment.controlPlan, assessment.evidenceChecklist);
  renderFrameworks(assessment.frameworkMap);
  renderQuestions(assessment.reviewQuestions);
  renderAuditTrail(assessment.auditTrail);
  fillForm(assessment.input);
  elements.exportJson.disabled = false;
  elements.exportBrief.disabled = false;
  refreshAssessmentList();
}

function showTab(tabName) {
  document.querySelectorAll(".result-tab").forEach((button) => button.classList.toggle("is-active", button.dataset.tab === tabName));
  document.querySelectorAll(".result-panel").forEach((panel) => {
    panel.hidden = panel.dataset.panel !== tabName;
  });
}

async function submitAssessment(event) {
  event.preventDefault();
  elements.runButton.disabled = true;
  elements.runButton.textContent = "Running screening...";
  elements.formError.textContent = "";
  try {
    const assessment = await fetchJson("/api/assessments", { method: "POST", body: JSON.stringify(assessmentPayload()) });
    renderAssessment(assessment);
    showTab("risks");
  } catch (error) {
    elements.formError.textContent = error.message;
  } finally {
    elements.runButton.disabled = false;
    elements.runButton.textContent = "Run governance screening";
  }
}

async function submitReview(event) {
  event.preventDefault();
  elements.reviewError.textContent = "";
  if (!currentAssessment) return;
  const formData = new FormData(elements.reviewForm);
  try {
    const assessment = await fetchJson(`/api/assessments/${currentAssessment.assessmentId}/review`, {
      method: "POST",
      body: JSON.stringify({ status: formData.get("status"), reviewer: formData.get("reviewer"), note: formData.get("note") })
    });
    elements.reviewForm.elements.namedItem("note").value = "";
    renderAssessment(assessment);
    showTab("review");
  } catch (error) {
    elements.reviewError.textContent = error.message;
  }
}

async function refreshAssessmentList() {
  const body = await fetchJson("/api/assessments");
  elements.count.textContent = body.assessments.length;
  const buttons = body.assessments.map((assessment) => {
    const button = document.createElement("button");
    if (assessment.assessmentId === currentAssessment?.assessmentId) button.classList.add("is-active");
    button.append(makeElement("strong", "", assessment.name), makeElement("small", "", `${titleCase(assessment.riskLevel)} | ${titleCase(assessment.status)}`));
    button.addEventListener("click", async () => renderAssessment(await fetchJson(`/api/assessments/${assessment.assessmentId}`)));
    return button;
  });
  elements.list.replaceChildren(...buttons);
}

function resetWorkspace() {
  currentAssessment = null;
  elements.form.reset();
  initializeForm(metadata);
  elements.form.elements.namedItem("name").value = "AI hiring support assistant";
  elements.form.elements.namedItem("assessor").value = "John Doe";
  elements.form.elements.namedItem("description").value = "An AI assistant summarizes resumes and recommends candidates for recruiter review. It processes applicant information but cannot automatically reject a candidate.";
  elements.form.elements.namedItem("humanReview").checked = true;
  elements.output.hidden = true;
  elements.emptyState.hidden = false;
  elements.pageTitle.textContent = "New AI system assessment";
  elements.saveStatus.textContent = "Not assessed";
  elements.exportJson.disabled = true;
  elements.exportBrief.disabled = true;
  elements.formError.textContent = "";
  refreshAssessmentList();
}

function governanceBrief(assessment) {
  const lines = [
    `# ${assessment.input.name}`,
    "",
    `Assessment ID: ${assessment.assessmentId}`,
    `Status: ${titleCase(assessment.status)}`,
    `Risk level: ${titleCase(assessment.riskLevel)} (${assessment.overallScore})`,
    `Recommendation: ${titleCase(assessment.decision.outcome)}`,
    "",
    "## Summary",
    "",
    assessment.summary,
    "",
    "## Risk Register",
    "",
    ...assessment.riskRegister.map((risk) => `- **${risk.title}** (${risk.rating}, residual ${risk.residualScore}): ${risk.description}`),
    "",
    "## Evidence Checklist",
    "",
    ...assessment.evidenceChecklist.map((item) => `- [ ] ${item.artifact} — ${item.owner} — ${item.status}`),
    "",
    "## Reviewer Questions",
    "",
    ...assessment.reviewQuestions.map((question, index) => `${index + 1}. ${question}`),
    "",
    "## Limitations",
    "",
    ...assessment.limitations.map((item) => `- ${item}`)
  ];
  return lines.join("\n");
}

function saveFile(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

document.querySelectorAll(".result-tab").forEach((button) => button.addEventListener("click", () => showTab(button.dataset.tab)));
elements.form.addEventListener("submit", submitAssessment);
elements.reviewForm.addEventListener("submit", submitReview);
elements.newButton.addEventListener("click", resetWorkspace);
elements.exportJson.addEventListener("click", () => saveFile(`${currentAssessment.assessmentId}.json`, JSON.stringify(currentAssessment, null, 2), "application/json"));
elements.exportBrief.addEventListener("click", () => saveFile(`${currentAssessment.assessmentId}.md`, governanceBrief(currentAssessment), "text/markdown"));

Promise.all([fetchJson("/api/meta"), fetchJson("/api/assessments")])
  .then(([meta, body]) => {
    metadata = meta;
    initializeForm(meta);
    elements.count.textContent = body.assessments.length;
    if (body.assessments.length) {
      return fetchJson(`/api/assessments/${body.assessments[0].assessmentId}`).then(renderAssessment);
    }
    return refreshAssessmentList();
  })
  .catch((error) => {
    elements.formError.textContent = `Start the local server, then reload. ${error.message}`;
  });
