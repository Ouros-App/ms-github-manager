const $ = (s) => document.querySelector(s);
const form = $("#repoForm");
const statusForm = $("#statusForm");
const modeBtns = [...document.querySelectorAll(".mode-tab")];

let mode = "bare";
let pollRef = null;
let activeCreationId = "";

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
  if (!res.ok) throw new Error((data && data.detail) || "Falha na requisicao");
  return data;
}

function setOutput(id, value) {
  $(id).textContent = pretty(value);
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
      ? "Cria um repositorio vazio com scaffold e workflow conforme a stack."
      : "Cria um repositorio a partir de um template existente na organizacao.";
  $("#submitBtn").textContent =
    nextMode === "bare" ? "Criar repositorio" : "Criar usando template";
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
  statusForm.elements.creation_id.value = id;
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
    return raw;
  }
  delete raw.language;
  return raw;
}

async function submitCreation(event) {
  event.preventDefault();
  const url = mode === "bare" ? "/repositories/bare" : "/repositories/from-template";
  const payload = collectPayload();
  setOutput("#resultBox", { status: "sending", payload });
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
  $("#repoVisibility").value = "private";
  $("#repoLanguage").value = "fastapi";
}

modeBtns.forEach((btn) => {
  btn.addEventListener("click", () => setMode(btn.dataset.mode));
});

form.addEventListener("submit", submitCreation);

statusForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = new FormData(statusForm).get("creation_id");
  if (!id) return;
  try {
    await startTracking(id);
  } catch (err) {
    setTrackingBadge("Falhou", "failed");
    setOutput("#statusBox", { error: err.message });
  }
});

$("#refreshTemplates").addEventListener("click", loadTemplates);
$("#resetBtn").addEventListener("click", resetForm);
$("#stopTracking").addEventListener("click", () => {
  stopPolling();
  activeCreationId = "";
  setTrackingBadge("Inativo", "idle");
});

setMode("bare");
loadHealth();
loadTemplates();
