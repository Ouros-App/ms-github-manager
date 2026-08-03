const $ = (s) => document.querySelector(s);
const form = $("#repoForm");
const modeBtns = [...document.querySelectorAll(".mode-tab")];

let mode = "bare";
let pollRef = null;
let activeCreationId = "";

function isPostgresTemplateName(value) {
  const normalized = String(value || "").toLowerCase();
  return normalized.includes("postgres") || normalized.includes("postgresql");
}

function isMongoTemplateName(value) {
  const normalized = String(value || "").toLowerCase();
  return normalized.includes("mongodb") || normalized.includes("mongo");
}

function pretty(v) {
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}

async function req(url, opt = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(opt.headers || {}) },
    ...opt,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data?.detail ?? data ?? "Falha na requisicao";
    throw new Error(typeof detail === "string" ? detail : pretty(detail));
  }
  return data;
}

function setOutput(id, value) {
  $(id).textContent = pretty(value);
}

function syncTemplateWarning() {
  const warning = $("#templateWarning");
  const suffix = $("#nameSuffix");
  const postgres = $("#postgresFields");
  const mongodb = $("#mongodbFields");
  const input = $("#repoName");
  if (!warning) return;
  const selected = $("#templateSelect")?.value || "";
  const isPostgres = isPostgresTemplateName(selected);
  const isMongo = isMongoTemplateName(selected);
  const showPostgres = mode === "template" && isPostgres && !isMongo;
  const showMongo = mode === "template" && isMongo && !isPostgres;
  const show = showPostgres || showMongo;
  warning.classList.toggle("is-hidden", !show);
  suffix?.classList.toggle("is-hidden", !show);
  input?.classList.toggle("with-suffix", show);
  postgres?.classList.toggle("is-hidden", !showPostgres);
  mongodb?.classList.toggle("is-hidden", !showMongo);
  postgres?.querySelectorAll("input").forEach((input) => {
    input.required = showPostgres;
  });
  mongodb?.querySelectorAll("input").forEach((input) => {
    input.required = showMongo;
  });
  input.placeholder = show ? "ms-orders" : "ms-orders-api";
}

function setMode(nextMode) {
  mode = nextMode;
  for (const btn of modeBtns) {
    btn.classList.toggle("is-active", btn.dataset.mode === nextMode);
  }
  $("#languageField").classList.toggle("is-hidden", nextMode !== "bare");
  $("#templateField").classList.toggle("is-hidden", nextMode !== "template");
  $("#modeHint").textContent =
    nextMode === "bare"
      ? "Cria um repositorio cru com .gitignore e workflow generico por padrao."
      : "Cria um repositorio a partir de um template existente na organizacao.";
  $("#submitBtn").textContent =
    nextMode === "bare" ? "Criar repositorio" : "Criar usando template";
  syncTemplateWarning();
}

function setTrackingBadge(text, state) {
  const el = $("#trackingBadge");
  el.textContent = text;
  el.dataset.state = state;
}

function stopPolling() {
  if (pollRef) {
    clearInterval(pollRef);
    pollRef = null;
  }
}

function resetTimeline() {
  $("#stepsList").innerHTML = '<li class="empty">Nenhuma etapa registrada.</li>';
}

function renderTimeline(steps) {
  const list = $("#stepsList");
  if (!steps || !steps.length) {
    resetTimeline();
    return;
  }
  list.innerHTML = steps.map((step) => `<li>${step}</li>`).join("");
}

function updateRepoLink(url) {
  const link = $("#trackedUrl");
  if (url) {
    link.href = url;
    link.textContent = "Abrir repositorio no GitHub";
    link.classList.remove("is-disabled");
  } else {
    link.removeAttribute("href");
    link.textContent = "Repositorio no GitHub";
    link.classList.add("is-disabled");
  }
}

function renderCreation(data) {
  $("#trackedId").textContent = data.creation_id || "-";
  $("#trackedRepo").textContent = data.repository || "-";
  $("#trackedMode").textContent = data.mode || "-";
  $("#trackedState").textContent = data.status || "-";
  $("#trackedStep").textContent = data.current_step || "Aguardando processamento.";
  updateRepoLink(data.url);
  renderTimeline(data.steps || []);
  setOutput("#statusBox", data);

  if (data.status === "queued" || data.status === "running") {
    setTrackingBadge("Acompanhando", "running");
  } else if (data.status === "done") {
    setTrackingBadge("Concluida", "done");
  } else if (data.status === "failed") {
    setTrackingBadge("Falhou", "failed");
  } else {
    setTrackingBadge("Inativo", "idle");
  }
}

async function loadHealth() {
  try {
    const data = await req("/health");
    $("#serviceStatus").textContent = data.status === "ok" ? "Online" : data.status;
    $("#orgName").textContent = data.organization || "-";
    $("#defaultBranch").textContent = data.default_branch || "-";
  } catch (err) {
    $("#serviceStatus").textContent = "Erro";
    setOutput("#resultBox", { error: err.message });
  }
}

async function loadTemplates() {
  const list = $("#templatesList");
  const select = $("#templateSelect");
  list.innerHTML = "";
  select.innerHTML = "";
  try {
    const templates = await req("/templates");
    $("#templateCount").textContent = String(templates.length);
    if (!templates.length) {
      list.innerHTML = '<div class="template-card empty">Nenhum template encontrado.</div>';
      select.innerHTML = '<option value="">Nenhum template</option>';
      return;
    }
    for (const item of templates) {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = item.name;
      select.appendChild(option);

      const card = document.createElement("a");
      card.className = "template-card";
      card.href = item.url;
      card.target = "_blank";
      card.rel = "noreferrer";
      card.innerHTML = `
        <strong>${item.name}</strong>
        <span>${item.description || "Sem descricao"}</span>
        <small>${item.private ? "privado" : "publico"}</small>
      `;
      list.appendChild(card);
    }
    syncTemplateWarning();
  } catch (err) {
    list.innerHTML = '<div class="template-card empty">Falha ao carregar templates.</div>';
    setOutput("#resultBox", { error: err.message });
  }
}

async function fetchCreation(id) {
  const data = await req(`/repositories/creations/${encodeURIComponent(id)}`);
  renderCreation(data);
  return data;
}

async function startTracking(id) {
  activeCreationId = id;
  stopPolling();
  const first = await fetchCreation(id);
  if (first.status === "done" || first.status === "failed") return;
  pollRef = setInterval(async () => {
    try {
      const current = await fetchCreation(id);
      if (current.status === "done" || current.status === "failed") {
        stopPolling();
      }
    } catch (err) {
      stopPolling();
      setTrackingBadge("Erro", "failed");
      setOutput("#statusBox", { error: err.message, creation_id: id });
    }
  }, 2000);
}

function collectPayload() {
  const raw = Object.fromEntries(new FormData(form).entries());
  if (!raw.description) delete raw.description;
  if (mode === "bare") {
    delete raw.template_name;
    Object.keys(raw).filter((key) => key.startsWith("postgres_") || key.startsWith("mongodb_")).forEach((key) => delete raw[key]);
    raw.language = "generic";
    return raw;
  }
  if (isPostgresTemplateName(raw.template_name || "")) {
    raw.name = `${String(raw.name || "").replace(/-database$/i, "").slice(0, 91)}-database`;
    raw.postgres = {
      host: raw.postgres_host,
      port: Number(raw.postgres_port),
      database: raw.postgres_database,
      user: raw.postgres_user,
      password: raw.postgres_password,
      root_database: raw.postgres_root_database,
      root_user: raw.postgres_root_user,
      root_password: raw.postgres_root_password,
    };
  }
  if (isMongoTemplateName(raw.template_name || "")) {
    raw.name = `${String(raw.name || "").replace(/-database$/i, "").slice(0, 91)}-database`;
    raw.mongodb = { connection_url: raw.mongodb_connection_url };
  }
  Object.keys(raw).filter((key) => key.startsWith("postgres_") || key.startsWith("mongodb_")).forEach((key) => delete raw[key]);
  delete raw.language;
  return raw;
}

function validateBeforeSubmit(payload) {
  if (mode === "template" && (isPostgresTemplateName(payload.template_name || "") || isMongoTemplateName(payload.template_name || "")) && !String(payload.name || "").replace(/-database$/i, "").trim()) {
    throw new Error("Informe o nome base do repositorio antes do sufixo '-database'.");
  }
}

async function submitCreation(event) {
  event.preventDefault();
  const url = mode === "bare" ? "/repositories/bare" : "/repositories/from-template";
  const payload = collectPayload();
  validateBeforeSubmit(payload);
  const safePayload = structuredClone(payload);
  if (safePayload.postgres) {
    safePayload.postgres.password = "[oculta]";
    safePayload.postgres.root_password = "[oculta]";
  }
  if (safePayload.mongodb) safePayload.mongodb.connection_url = "[oculta]";
  setOutput("#resultBox", { status: "sending", payload: safePayload });
  try {
    const data = await req(url, { method: "POST", body: JSON.stringify(payload) });
    setOutput("#resultBox", data);
    resetTimeline();
    await startTracking(data.creation_id);
  } catch (err) {
    setOutput("#resultBox", { error: err.message });
    setTrackingBadge("Falhou", "failed");
  }
}

function resetForm() {
  form.reset();
  if ($("#templateSelect").options.length) $("#templateSelect").selectedIndex = 0;
}

modeBtns.forEach((btn) => {
  btn.addEventListener("click", () => setMode(btn.dataset.mode));
});

form.addEventListener("submit", submitCreation);

$("#refreshTemplates").addEventListener("click", loadTemplates);
$("#resetBtn").addEventListener("click", resetForm);
$("#templateSelect")?.addEventListener("change", syncTemplateWarning);
$("#stopTracking").addEventListener("click", () => {
  stopPolling();
  activeCreationId = "";
  setTrackingBadge("Inativo", "idle");
  $("#trackedStep").textContent = "Acompanhamento pausado.";
});

setMode("bare");
loadHealth();
loadTemplates();
