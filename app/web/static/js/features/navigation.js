import {byId} from "../core/http.js";

const pages = {
  config: {
    eyebrow: "WORKSPACE · CONFIG",
    title: "任务配置",
    description: "设置搜索条件、维护任务队列并控制 BOSS 执行器。",
  },
  history: {
    eyebrow: "WORKSPACE · HISTORY",
    title: "历史任务",
    description: "回看已结束的搜索记录；历史任务不可修改，只能重新添加。"
  },
  jobs: {
    eyebrow: "WORKSPACE · JOB RECORDS",
    title: "岗位记录",
    description: "查看浏览器遍历过的岗位详情、访问次数和打招呼状态。",
  },
  assistant: {
    eyebrow: "WORKSPACE · AI ASSISTANT",
    title: "AI 求职助手",
    description: "通过对话创建、修改、取消和调整搜索任务。",
  },
};

function setSidebarOpen(open) {
  document.body.classList.toggle("sidebar-open", open);
  byId("menu-toggle").setAttribute("aria-expanded", String(open));
}

export function showPage(requestedPage, updateHash = true) {
  const page = pages[requestedPage] ? requestedPage : "config";
  document.querySelectorAll(".page-view").forEach((view) => {
    const active = view.dataset.page === page;
    view.hidden = !active;
    view.classList.toggle("active", active);
  });
  document.querySelectorAll(".nav-item").forEach((item) => {
    const active = item.dataset.page === page;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  byId("page-eyebrow").textContent = pages[page].eyebrow;
  byId("page-title").textContent = pages[page].title;
  byId("page-description").textContent = pages[page].description;
  document.title = `${pages[page].title} · Boss Agent`;
  if (updateHash && window.location.hash !== `#${page}`) {
    window.history.replaceState(null, "", `#${page}`);
  }
  setSidebarOpen(false);
  window.dispatchEvent(new CustomEvent("boss:page-change", {detail: page}));
}

export function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => showPage(item.dataset.page));
  });
  byId("menu-toggle").addEventListener("click", () => {
    setSidebarOpen(!document.body.classList.contains("sidebar-open"));
  });
  byId("sidebar-backdrop").addEventListener("click", () => setSidebarOpen(false));
  window.addEventListener("hashchange", () => showPage(window.location.hash.slice(1), false));
  showPage(window.location.hash.slice(1), false);
}
