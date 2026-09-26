import {byId, toast} from "./js/core/http.js";
import {setupNavigation} from "./js/features/navigation.js";
import {setupAssistant} from "./js/features/assistant.js";
import {loadGlobalConfig, setupGlobalConfig} from "./js/features/global_config.js";
import {setupJobRecords} from "./js/features/job_records.js?v=20260925-1";
import {
  loadExecution,
  loadOptions,
  loadTasks,
  openBrowser,
  setupTasks,
  startQueue,
  stopQueue,
} from "./js/features/tasks.js";

function report(action) {
  return action.catch((error) => toast(error.message));
}

window.addEventListener("DOMContentLoaded", async () => {
  setupGlobalConfig();
  setupTasks();
  setupAssistant();
  setupJobRecords();
  setupNavigation();

  byId("start-queue-btn").addEventListener("click", () => report(startQueue()));
  byId("stop-btn").addEventListener("click", () => report(stopQueue()));
  byId("login-btn").addEventListener("click", () => report(openBrowser()));

  try {
    await loadOptions();
    await Promise.all([
      loadTasks(),
      loadExecution(),
      loadGlobalConfig(),
    ]);
  } catch (error) {
    toast(error.message);
  }
});
