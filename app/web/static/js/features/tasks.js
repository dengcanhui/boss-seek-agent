import {api, byId, escapeHtml, toast} from "../core/http.js";

const optionState = {};
let allTasks = [];
let execution = {active: false, current_job_seek_task_id: null, last_error: null};
let editingTaskId = null;
let editorReturnFocus = null;

const singleFields = ["city", "jobType", "salary"];
const multiFields = ["experience", "degree", "scale", "industry", "stage"];
const choiceFields = ["jobType", "salary", "experience", "degree", "scale", "stage"];
const searchableFields = ["city", "industry"];
const statusLabels = {
  pending: "待执行",
  running: "执行中",
  completed: "已完成",
  stopped: "已停止",
  failed: "失败",
  cancelled: "已取消",
};

function optionNames(field, {excludeUnlimited = false} = {}) {
  const mapping = optionState[field] || {};
  return Object.keys(mapping).filter((name) => !(excludeUnlimited && name === "不限"));
}

function displayName(field, code) {
  const mapping = optionState[field] || {};
  const hit = Object.entries(mapping).find(([, value]) => String(value) === String(code));
  return hit?.[0] || code || "不限";
}

function displayNames(field, values = []) {
  return (values || []).map((value) => displayName(field, value)).filter(Boolean);
}

function optionNode(name) {
  const option = document.createElement("option");
  option.value = name;
  option.textContent = name;
  return option;
}

function fillSelect(id, names) {
  byId(id).replaceChildren(...names.map(optionNode));
}

function selectedNames(id) {
  return [...byId(id).selectedOptions].filter((option) => option.value).map((option) => option.value);
}

function selectedOption(id) {
  return [...byId(id).selectedOptions].find((option) => option.value) || null;
}

function writeSelectedName(id) {
  if (id !== "city") return;
  const option = selectedOption(id);
  byId("city-search").value = option?.textContent || "";
}

function renderChoices(id) {
  const container = byId(`${id}-choices`);
  if (!container) return;
  container.replaceChildren(...[...byId(id).options].filter((option) => option.value).map((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `choice-button${option.selected ? " selected" : ""}`;
    button.textContent = option.textContent;
    button.setAttribute("aria-pressed", String(option.selected));
    button.addEventListener("click", () => chooseValue(id, option.value));
    return button;
  }));
}

function renderSelectedChips(id) {
  const container = byId(`${id}-selected`);
  if (!container) return;
  const selected = [...byId(id).selectedOptions].filter((option) => option.value);
  container.classList.toggle("hidden", !selected.length);
  container.replaceChildren(...selected.map((option) => {
    const chip = document.createElement("span");
    chip.className = "selection-chip";
    chip.append(document.createTextNode(option.textContent));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `移除${option.textContent}`);
    remove.addEventListener("click", () => {
      option.selected = false;
      renderSelectedChips(id);
    });
    chip.append(remove);
    return chip;
  }));
}

function refreshOptionControl(id) {
  if (choiceFields.includes(id)) renderChoices(id);
  if (id === "industry") renderSelectedChips(id);
  writeSelectedName(id);
}

function chooseValue(id, value) {
  const select = byId(id);
  const target = [...select.options].find((option) => option.value === String(value));
  if (!target) return;
  if (select.multiple) {
    target.selected = !target.selected;
  } else if (id !== "city" && target.selected) {
    [...select.options].forEach((option) => { option.selected = option.value === ""; });
  } else {
    [...select.options].forEach((option) => { option.selected = option === target; });
  }
  refreshOptionControl(id);
}

function setSelectedValues(id, values) {
  const wanted = new Set((values || []).filter(Boolean).map(String));
  [...byId(id).options].forEach((option) => { option.selected = wanted.has(option.value); });
  refreshOptionControl(id);
}

function clearStaleCity(text) {
  const selected = selectedOption("city");
  if (selected && text.trim() === selected.textContent) return;
  [...byId("city").options].forEach((option) => { option.selected = false; });
}

function searchOptions(id) {
  const input = byId(`${id}-search`);
  const results = byId(`${id}-results`);
  const query = input.value.trim().toLocaleLowerCase("zh-CN");
  const currentCity = id === "city" ? selectedOption("city")?.textContent || "" : "";
  if (!query || query === currentCity.toLocaleLowerCase("zh-CN")) {
    results.classList.add("hidden");
    results.replaceChildren();
    return;
  }
  const matches = [...byId(id).options]
    .filter((option) => option.value && !option.selected && option.textContent.toLocaleLowerCase("zh-CN").includes(query))
    .slice(0, 12);
  if (!matches.length) {
    const empty = document.createElement("div");
    empty.className = "picker-empty";
    empty.textContent = "没有匹配项";
    results.replaceChildren(empty);
  } else {
    results.replaceChildren(...matches.map((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "picker-result";
      button.textContent = option.textContent;
      button.setAttribute("role", "option");
      button.addEventListener("click", () => {
        chooseValue(id, option.value);
        results.classList.add("hidden");
        if (id === "industry") input.value = "";
        else input.select();
        input.focus();
      });
      return button;
    }));
  }
  results.classList.remove("hidden");
}

function setupSearchPicker(id) {
  const picker = byId(`${id}-picker`);
  const input = byId(`${id}-search`);
  const results = byId(`${id}-results`);
  input.addEventListener("input", () => {
    if (id === "city") clearStaleCity(input.value);
    searchOptions(id);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      results.classList.add("hidden");
      if (id === "city") writeSelectedName(id);
      else input.value = "";
    } else if (event.key === "Enter") {
      const first = results.querySelector(".picker-result");
      if (first) {
        event.preventDefault();
        first.click();
      }
    }
  });
  document.addEventListener("click", (event) => {
    if (!picker.contains(event.target)) results.classList.add("hidden");
  });
}

export async function loadOptions() {
  const data = await api("/api/job-seek-tasks/options");
  Object.assign(optionState, data || {});
  fillSelect("city", ["", ...optionNames("city", {excludeUnlimited: true})]);
  fillSelect("industry", optionNames("industry", {excludeUnlimited: true}));
  fillSelect("jobType", ["", ...optionNames("jobType", {excludeUnlimited: true})]);
  fillSelect("salary", ["", ...optionNames("salary", {excludeUnlimited: true})]);
  for (const field of ["experience", "degree", "scale", "stage"]) {
    fillSelect(field, optionNames(field, {excludeUnlimited: true}));
  }
  choiceFields.forEach(renderChoices);
  searchableFields.forEach(setupSearchPicker);
  renderSelectedChips("industry");
  resetTaskEditor();
}

function resetTaskEditor() {
  byId("query").value = "";
  byId("city-search").value = "";
  byId("industry-search").value = "";
  singleFields.forEach((id) => setSelectedValues(id, []));
  multiFields.forEach((id) => setSelectedValues(id, []));
  byId("task-priority").value = "0";
}

function taskPayload() {
  const city = selectedNames("city")[0];
  const query = byId("query").value.trim();
  if (!city) throw new Error("请选择城市");
  if (!query) throw new Error("请填写搜索关键词");
  return {
    query,
    city,
    jobType: selectedNames("jobType")[0] || null,
    salary: selectedNames("salary")[0] || null,
    experience: selectedNames("experience"),
    degree: selectedNames("degree"),
    scale: selectedNames("scale"),
    industry: selectedNames("industry"),
    stage: selectedNames("stage"),
    priority: Number(byId("task-priority").value || 0),
  };
}

function populateTaskEditor(task) {
  const config = task.config || {};
  byId("query").value = config.query || "";
  setSelectedValues("city", config.city ? [displayName("city", config.city)] : []);
  setSelectedValues("jobType", config.jobType ? [displayName("jobType", config.jobType)] : []);
  setSelectedValues("salary", config.salary ? [displayName("salary", config.salary)] : []);
  for (const field of multiFields) {
    setSelectedValues(field, displayNames(field, config[field] || []).filter((name) => name !== "不限"));
  }
  byId("task-priority").value = String(task.priority ?? 0);
}

function showEditorError(message) {
  const node = byId("task-editor-error");
  node.textContent = message;
  node.classList.remove("hidden");
}

function clearEditorError() {
  byId("task-editor-error").classList.add("hidden");
}

function showEditor() {
  editorReturnFocus = document.activeElement;
  clearEditorError();
  byId("task-editor").classList.remove("hidden");
  document.body.classList.add("modal-open");
  requestAnimationFrame(() => byId("query").focus());
}

function closeEditor() {
  editingTaskId = null;
  clearEditorError();
  byId("task-editor").classList.add("hidden");
  document.body.classList.remove("modal-open");
  if (editorReturnFocus instanceof HTMLElement) editorReturnFocus.focus();
  editorReturnFocus = null;
}

function openNewTask() {
  if (execution.active) return;
  editingTaskId = null;
  resetTaskEditor();
  byId("task-editor-title").textContent = "新建搜索任务";
  byId("save-task-btn").textContent = "保存任务";
  showEditor();
}

function openEditTask(taskId) {
  if (execution.active) return;
  const task = allTasks.find((item) => item.id === taskId);
  if (!task || task.status !== "pending") return;
  editingTaskId = taskId;
  resetTaskEditor();
  populateTaskEditor(task);
  byId("task-editor-title").textContent = `编辑搜索任务 #${task.id}`;
  byId("save-task-btn").textContent = "保存修改";
  showEditor();
}

async function saveTask() {
  clearEditorError();
  let payload;
  try {
    payload = taskPayload();
    if (editingTaskId) {
      await api(`/api/job-seek-tasks/${editingTaskId}`, {method: "PATCH", body: payload});
    } else {
      await api("/api/job-seek-tasks", {method: "POST", body: payload});
    }
  } catch (error) {
    showEditorError(error.message);
    return;
  }
  toast(editingTaskId ? "任务已保存" : "搜索任务已创建");
  closeEditor();
  await loadTasks();
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function taskDetails(task) {
  const config = task.config || {};
  const values = [
    displayName("jobType", config.jobType),
    displayName("salary", config.salary),
    ...displayNames("experience", config.experience),
    ...displayNames("degree", config.degree),
    ...displayNames("industry", config.industry),
    ...displayNames("scale", config.scale),
    ...displayNames("stage", config.stage),
  ].filter((value) => value && value !== "不限");
  return values.join(" · ") || "不限条件";
}

function taskCard(task) {
  const config = task.config || {};
  const city = displayName("city", config.city);
  const editable = !execution.active && task.status === "pending";
  const cancellable = ["pending", "running"].includes(task.status);
  return `<article class="queue-task" data-task-id="${task.id}" data-status="${escapeHtml(task.status)}">
    <span class="task-priority" title="执行优先级，数字越小越先">${escapeHtml(String(task.priority ?? 0))}</span>
    <div class="queue-task-content">
      <div class="queue-task-meta"><span class="source-badge manual">搜索任务</span><span class="task-status ${escapeHtml(task.status)}">${escapeHtml(statusLabels[task.status] || task.status)}</span></div>
      <h3>${escapeHtml(config.query || "未命名搜索")}</h3>
      <p>${escapeHtml(`${city} · ${taskDetails(task)}`)}</p>
      <small><strong>${escapeHtml(city)} · ${escapeHtml(config.query || "未命名搜索")}</strong></small>
      <small>更新于 ${escapeHtml(formatTime(task.updated_at))}</small>
    </div>
    <div class="queue-task-actions">
      ${task.status === "pending" ? `<button class="text-button task-edit" data-task-id="${task.id}"${editable ? "" : " disabled"}>编辑</button>` : ""}
      ${cancellable ? `<button class="text-button danger task-cancel" data-task-id="${task.id}">${task.status === "running" ? "停止" : "取消"}</button>` : ""}
      ${task.status === "pending" ? `<button class="icon-button task-delete" data-task-id="${task.id}" aria-label="删除任务" title="删除任务"${execution.active ? " disabled" : ""}>×</button>` : ""}
    </div>
  </article>`;
}

function renderQueue() {
  const queue = allTasks
    .filter((task) => ["pending", "running"].includes(task.status))
    .sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0) || new Date(a.created_at) - new Date(b.created_at));
  const container = byId("search-tasks-list");
  if (!queue.length) {
    container.innerHTML = `<div class="task-empty"><strong>还没有待执行任务</strong><p>点击“新建搜索任务”，或让 AI 助手按城市和关键词生成任务。</p></div>`;
    renderExecution();
    return;
  }
  const pendingCount = queue.filter((task) => task.status === "pending").length;
  container.innerHTML = `<section class="queue-section"><div class="queue-heading"><strong>执行队列</strong><span>${pendingCount} 个待执行</span></div><div class="queue-list">${queue.map(taskCard).join("")}</div></section>`;
  renderExecution();
}

function historyRow(task) {
  const config = task.config || {};
  const city = displayName("city", config.city);
  return `<tr data-task-id="${task.id}">
    <td><strong>${escapeHtml(config.query || "未命名搜索")}</strong><small>#${task.id}</small></td>
    <td>${escapeHtml(`${city} · ${taskDetails(task)}`)}</td>
    <td>${escapeHtml(String(task.priority ?? 0))}</td>
    <td><span class="task-status ${escapeHtml(task.status)}">${escapeHtml(statusLabels[task.status] || task.status)}</span></td>
    <td>${escapeHtml(formatTime(task.updated_at))}</td>
    <td class="history-actions"><button class="text-button task-requeue" data-task-id="${task.id}">重新添加</button></td>
  </tr>`;
}

function renderHistory() {
  const history = allTasks.filter((task) => !["pending", "running"].includes(task.status));
  byId("history-tasks-body").innerHTML = history.length
    ? history.map(historyRow).join("")
    : `<tr><td colspan="6" class="muted">还没有已结束的搜索任务</td></tr>`;
}

export async function loadTasks() {
  const [activeTasks, historyTasks] = await Promise.all([
    api("/api/job-seek-tasks?limit=500&statuses=pending&statuses=running"),
    api("/api/job-seek-tasks?limit=200&statuses=completed&statuses=failed&statuses=stopped&statuses=cancelled"),
  ]);
  allTasks = [...activeTasks, ...historyTasks];
  renderQueue();
  renderHistory();
}

function renderExecution() {
  const active = Boolean(execution.active);
  const currentId = execution.current_job_seek_task_id;
  const statusDot = byId("status-dot");
  statusDot.classList.toggle("active", active && !execution.last_error);
  statusDot.classList.toggle("error", Boolean(execution.last_error));
  byId("task-status").textContent = execution.last_error ? "执行异常" : active ? "运行中" : "空闲";
  byId("task-message").textContent = execution.last_error || (currentId ? `正在处理任务 #${currentId}` : active ? "等待下一条任务" : "等待开始");
  byId("progress-bar").style.width = active ? "100%" : "0%";
  byId("progress-bar").parentElement.setAttribute("aria-valuenow", active ? "100" : "0");
  byId("start-queue-btn").disabled = active || !allTasks.some((task) => task.status === "pending");
  byId("stop-btn").disabled = !active;
  byId("new-task-btn").disabled = active;
  byId("login-btn").disabled = active;
  byId("save-task-btn").disabled = active;
  document.querySelectorAll(".task-edit, .task-requeue, .task-delete").forEach((button) => {
    button.disabled = active || button.closest("[data-status]")?.dataset.status === "running";
  });
}

export async function loadExecution() {
  execution = await api("/api/execution");
  renderExecution();
}

export async function startQueue() {
  execution = await api("/api/execution/start", {method: "POST"});
  renderExecution();
  await loadTasks();
  toast("执行器已启动");
}

export async function stopQueue() {
  execution = await api("/api/execution/stop", {method: "POST"});
  renderExecution();
  await loadTasks();
  toast("执行器已停止");
}

export async function openBrowser() {
  await api("/api/execution/browser/open", {method: "POST"});
  toast("浏览器已打开，请在 BOSS 页面完成登录");
}

async function cancelTask(taskId) {
  await api(`/api/job-seek-tasks/${taskId}/cancel`, {method: "POST"});
  toast(`任务 #${taskId} 已停止`);
  await Promise.all([loadTasks(), loadExecution()]);
}

async function requeueTask(taskId) {
  await api(`/api/job-seek-tasks/${taskId}/requeue`, {method: "POST"});
  toast("已重新添加到待执行队列");
  await loadTasks();
}

async function deleteTask(taskId) {
  const task = allTasks.find((item) => item.id === taskId);
  if (!task || task.status !== "pending") return;
  if (!window.confirm(`确定删除任务 #${taskId} 吗？`)) return;
  await api(`/api/job-seek-tasks/${taskId}`, {method: "DELETE"});
  toast("任务已删除");
  await loadTasks();
}

async function handleTaskAction(event) {
  const button = event.target.closest("[data-task-id]");
  if (!button) return;
  const taskId = Number(button.dataset.taskId);
  try {
    if (button.classList.contains("task-edit")) openEditTask(taskId);
    else if (button.classList.contains("task-cancel")) await cancelTask(taskId);
    else if (button.classList.contains("task-requeue")) await requeueTask(taskId);
    else if (button.classList.contains("task-delete")) await deleteTask(taskId);
  } catch (error) {
    toast(error.message);
  }
}

export function setupTasks() {
  byId("new-task-btn").addEventListener("click", openNewTask);
  byId("cancel-task-edit").addEventListener("click", closeEditor);
  byId("task-editor-backdrop").addEventListener("click", closeEditor);
  byId("save-task-btn").addEventListener("click", () => saveTask().catch((error) => toast(error.message)));
  byId("refresh-search-tasks").addEventListener("click", () => loadTasks().catch((error) => toast(error.message)));
  byId("refresh-history-tasks").addEventListener("click", () => loadTasks().catch((error) => toast(error.message)));
  byId("search-tasks-list").addEventListener("click", handleTaskAction);
  byId("history-tasks-body").addEventListener("click", handleTaskAction);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !byId("task-editor").classList.contains("hidden")) closeEditor();
  });
  window.addEventListener("boss:tasks-refresh", () => loadTasks().catch((error) => toast(error.message)));
}
