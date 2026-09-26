import {api, byId, toast} from "../core/http.js";

const splitList = (value) => [...new Set(
  value
    .split(/\n|,|，/)
    .map((item) => item.trim())
    .filter(Boolean),
)];

function normalizeListInput(id) {
  byId(id).value = splitList(byId(id).value).join("\n");
}

export async function loadGlobalConfig() {
  const config = await api("/api/global-config");
  byId("company_blacklist").value = (config.company_blacklist || []).join("\n");
  byId("job_blacklist").value = (config.job_blacklist || []).join("\n");
  byId("description_blacklist").value = (config.description_blacklist || []).join("\n");
  byId("max_jobs_per_task").value = config.max_jobs_per_task ?? 100;
  byId("greet_wait_min").value = config.greet_wait_min_seconds ?? 8;
  byId("greet_wait_max").value = config.greet_wait_max_seconds ?? 15;
  byId("filter_inactive_over_week").checked = config.filter_inactive_over_week !== false;
}

export async function saveGlobalConfig() {
  const maxJobsPerTask = Number(byId("max_jobs_per_task").value || 0);
  const minWait = Number(byId("greet_wait_min").value || 0);
  const maxWait = Number(byId("greet_wait_max").value || 0);
  if (!Number.isInteger(maxJobsPerTask) || maxJobsPerTask < 1 || maxJobsPerTask > 1000) {
    throw new Error("单个搜索任务最大岗位数必须是 1~1000 的整数");
  }
  if (minWait > maxWait) throw new Error("打招呼后最小等待不能大于最大等待");

  const companyBlacklist = splitList(byId("company_blacklist").value);
  const jobBlacklist = splitList(byId("job_blacklist").value);
  const descriptionBlacklist = splitList(byId("description_blacklist").value);

  await api("/api/global-config", {
    method: "PATCH",
    body: {
      company_blacklist: companyBlacklist,
      job_blacklist: jobBlacklist,
      description_blacklist: descriptionBlacklist,
      max_jobs_per_task: maxJobsPerTask,
      greet_wait_min_seconds: minWait,
      greet_wait_max_seconds: maxWait,
      filter_inactive_over_week: byId("filter_inactive_over_week").checked,
    },
  });

  byId("company_blacklist").value = companyBlacklist.join("\n");
  byId("job_blacklist").value = jobBlacklist.join("\n");
  byId("description_blacklist").value = descriptionBlacklist.join("\n");
  toast("全局配置已保存，将从下一条执行任务开始生效");
}

export function setupGlobalConfig() {
  for (const id of ["company_blacklist", "job_blacklist", "description_blacklist"]) {
    byId(id).addEventListener("blur", () => normalizeListInput(id));
  }
  byId("save-global-config-btn").addEventListener("click", () => {
    saveGlobalConfig().catch((error) => toast(error.message));
  });
}
