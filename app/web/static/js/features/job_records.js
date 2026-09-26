import {api, byId, escapeHtml, toast} from "../core/http.js";

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function greetStatus(record) {
  if (record.greeted) {
    return `<span class="job-greet-status greeted">已打招呼</span>${record.greeted_at ? `<small>${escapeHtml(formatTime(record.greeted_at))}</small>` : ""}`;
  }

  const fallbackReason = record.contacted
    ? "已经与该岗位建立沟通关系"
    : "未记录未打招呼原因";
  const reason = record.not_greeted_reason?.trim() || fallbackReason;

  return `<div class="job-greet-result">
    <span class="job-greet-status pending">未打招呼</span>
    <div class="not-greeted-reason"><span>原因：</span>${escapeHtml(reason)}</div>
  </div>`;
}

function recordRow(record) {
  const boss = [record.boss_name, record.boss_title].filter(Boolean).join(" · ") || "—";
  const salaryLocation = [record.salary_desc, record.location_desc].filter(Boolean).join(" · ") || "—";
  return `<tr>
    <td><strong>${escapeHtml(record.job_name || "未命名岗位")}</strong><small>${escapeHtml(record.job_key)}</small></td>
    <td>${escapeHtml(record.company_name || "—")}</td>
    <td>${escapeHtml(salaryLocation)}</td>
    <td>${escapeHtml(boss)}${record.active_time_desc ? `<small>${escapeHtml(record.active_time_desc)}</small>` : ""}</td>
    <td><strong>${escapeHtml(String(record.visit_count || 0))} 次</strong>${record.last_task_id ? `<small>最近任务 #${escapeHtml(String(record.last_task_id))}</small>` : ""}</td>
    <td class="job-greet-cell">${greetStatus(record)}</td>
    <td>${escapeHtml(formatTime(record.last_seen_at))}</td>
    <td>
      <details class="job-record-detail" data-record-id="${record.id}">
        <summary>查看详情</summary>
        <div class="job-record-detail-panel"><p class="muted">展开后加载岗位详情…</p></div>
      </details>
    </td>
  </tr>`;
}

async function loadRecordDetail(details) {
  if (details.dataset.loaded === "true") return;
  const panel = details.querySelector(".job-record-detail-panel");
  try {
    const record = await api(`/api/job-records/${details.dataset.recordId}`);
    panel.innerHTML = `<strong>岗位描述</strong><p>${escapeHtml(record.description || "暂无岗位描述")}</p>`;
    details.dataset.loaded = "true";
  } catch (error) {
    panel.innerHTML = `<p class="history-error">${escapeHtml(error.message)}</p>`;
  }
}

function bindRecordDetails() {
  document.querySelectorAll(".job-record-detail").forEach((details) => {
    details.addEventListener("toggle", () => {
      if (details.open) loadRecordDetail(details);
    });
  });
}

export async function loadJobRecords() {
  const records = await api("/api/job-records?limit=200");
  byId("job-records-body").innerHTML = records.length
    ? records.map(recordRow).join("")
    : `<tr><td colspan="8" class="muted">还没有遍历过的岗位记录</td></tr>`;
  bindRecordDetails();
}

export function setupJobRecords() {
  byId("refresh-job-records").addEventListener("click", () => {
    loadJobRecords().catch((error) => toast(error.message));
  });
  window.addEventListener("boss:page-change", (event) => {
    if (event.detail === "jobs") {
      loadJobRecords().catch((error) => toast(error.message));
    }
  });
}
