import {api, byId, escapeHtml, toast} from "../core/http.js";

const SUGGESTIONS = [
  "在杭州找 Agent 开发岗位",
  "先搜上海，再搜杭州，薪资 20-50K",
  "看看现在队列里有哪些任务",
  "把不合适的任务取消掉",
];

const CONVERSATION_ID_KEY = "boss-agent-conversation-id";
let conversationId = localStorage.getItem(CONVERSATION_ID_KEY)
  || sessionStorage.getItem(CONVERSATION_ID_KEY)
  || crypto.randomUUID();
localStorage.setItem(CONVERSATION_ID_KEY, conversationId);

function setConversationId(value) {
  conversationId = value;
  localStorage.setItem(CONVERSATION_ID_KEY, value);
}

function turnMarkup(message) {
  const assistant = message.role === "assistant";
  return `<article class="chat-turn ${assistant ? "assistant" : "user"}">
    ${assistant ? `<span class="chat-avatar" aria-hidden="true">✦</span>` : ""}
    <div class="chat-body">
      <div class="chat-bubble">${escapeHtml(message.content)}</div>
      ${assistant ? `<div class="chat-actions"><button type="button" class="chat-copy">复制</button></div>` : ""}
    </div>
  </article>`;
}

function emptyMarkup() {
  return `<div class="chat-empty">
    <span class="chat-avatar large" aria-hidden="true">✦</span>
    <h3>说说你的求职方向</h3>
    <p>我会把偏好整理成搜索任务；之后也可以继续修改、取消任务，或者询问当前队列状态。</p>
    <div class="chat-suggestions">
      ${SUGGESTIONS.map((text) => `<button type="button" class="chat-suggestion">${escapeHtml(text)}</button>`).join("")}
    </div>
  </div>`;
}

function thinkingMarkup() {
  return `<article class="chat-turn assistant" id="chat-thinking">
    <span class="chat-avatar" aria-hidden="true">✦</span>
    <div class="chat-body"><div class="chat-bubble"><span class="chat-dots"><i></i><i></i><i></i></span></div></div>
  </article>`;
}

function formatConversationTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function conversationMarkup(conversation) {
  const active = conversation.conversation_id === conversationId;
  return `<button
      type="button"
      class="conversation-item${active ? " active" : ""}"
      data-conversation-id="${escapeHtml(conversation.conversation_id)}"
      title="${escapeHtml(conversation.title)}"
    >
      <span class="conversation-item-title">${escapeHtml(conversation.title)}</span>
      <span class="conversation-item-time">${escapeHtml(formatConversationTime(conversation.updated_at))}</span>
    </button>`;
}

function bindTurns(container) {
  container.querySelectorAll(".chat-copy").forEach((button) => {
    if (button.dataset.bound === "true") return;
    button.dataset.bound = "true";
    button.addEventListener("click", async () => {
      const bubble = button.closest(".chat-turn")?.querySelector(".chat-bubble");
      try {
        await navigator.clipboard.writeText(bubble?.textContent || "");
        button.textContent = "已复制";
        setTimeout(() => { button.textContent = "复制"; }, 1500);
      } catch {
        toast("复制失败，请手动选择文本");
      }
    });
  });
  container.querySelectorAll(".chat-suggestion").forEach((button) => {
    if (button.dataset.bound === "true") return;
    button.dataset.bound = "true";
    button.addEventListener("click", () => {
      const input = byId("chat-input");
      input.value = button.textContent;
      autoGrow(input);
      input.focus();
    });
  });
}

function clearPlaceholder(container) {
  if (container.querySelector(".chat-empty, .muted")) container.replaceChildren();
}

function appendTurn(message) {
  const container = byId("chat-messages");
  clearPlaceholder(container);
  container.insertAdjacentHTML("beforeend", turnMarkup(message));
  bindTurns(container);
  container.scrollTop = container.scrollHeight;
}

function appendThinking() {
  const container = byId("chat-messages");
  clearPlaceholder(container);
  container.insertAdjacentHTML("beforeend", thinkingMarkup());
  container.scrollTop = container.scrollHeight;
}

function autoGrow(input) {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
}

function renderConversationList(conversations) {
  const container = byId("conversation-list");
  if (!conversations.length) {
    container.innerHTML = `<p class="conversation-empty">还没有历史对话。发送第一条消息后会出现在这里。</p>`;
    byId("chat-current-title").textContent = "AI 求职助手";
    return;
  }

  container.innerHTML = conversations.map(conversationMarkup).join("");
  const current = conversations.find((item) => item.conversation_id === conversationId);
  byId("chat-current-title").textContent = current?.title || "新对话";

  container.querySelectorAll(".conversation-item").forEach((button) => {
    button.addEventListener("click", async () => {
      const nextId = button.dataset.conversationId;
      if (!nextId || nextId === conversationId) return;
      setConversationId(nextId);
      await loadConversations();
      await loadChatHistory();
      byId("chat-input").focus();
    });
  });
}

export function renderEmptyChat() {
  const container = byId("chat-messages");
  container.innerHTML = emptyMarkup();
  bindTurns(container);
}

export async function loadConversations({selectLatestIfMissing = false} = {}) {
  const conversations = await api("/api/chat/conversations?limit=50");
  const currentExists = conversations.some((item) => item.conversation_id === conversationId);

  if (selectLatestIfMissing && conversations.length && !currentExists) {
    setConversationId(conversations[0].conversation_id);
  }

  renderConversationList(conversations);
  return conversations;
}

export async function loadChatHistory() {
  const requestedConversationId = conversationId;
  const messages = await api(`/api/chat?conversation_id=${encodeURIComponent(requestedConversationId)}&limit=100`);
  if (requestedConversationId !== conversationId) return;

  const container = byId("chat-messages");
  if (!messages.length) {
    renderEmptyChat();
    return;
  }

  container.innerHTML = messages.map(turnMarkup).join("");
  bindTurns(container);
  container.scrollTop = container.scrollHeight;
}

function startNewConversation() {
  setConversationId(crypto.randomUUID());
  byId("chat-current-title").textContent = "新对话";
  renderEmptyChat();
  loadConversations().catch((error) => toast(error.message));
  byId("chat-input").focus();
}

export async function sendChatMessage() {
  const input = byId("chat-input");
  const content = input.value.trim();
  if (!content) return;

  const requestConversationId = conversationId;
  const button = byId("chat-send");
  button.disabled = true;
  input.value = "";
  autoGrow(input);
  appendTurn({role: "user", content});
  appendThinking();

  try {
    const response = await api("/api/chat", {
      method: "POST",
      body: {conversation_id: requestConversationId, message: content},
    });

    if (conversationId === requestConversationId) {
      byId("chat-thinking")?.remove();
      appendTurn({role: "assistant", content: response.reply || "这一步没有产生可显示的回复。"});
    }
    await loadConversations();
    window.dispatchEvent(new Event("boss:tasks-refresh"));
  } catch (error) {
    if (conversationId === requestConversationId) byId("chat-thinking")?.remove();
    toast(error.message);
  } finally {
    button.disabled = false;
    input.focus();
  }
}

export function setupAssistant() {
  const input = byId("chat-input");
  input.addEventListener("input", () => autoGrow(input));
  byId("chat-send").addEventListener("click", () => sendChatMessage());
  byId("new-conversation").addEventListener("click", startNewConversation);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      sendChatMessage();
    }
  });
  autoGrow(input);

  loadConversations({selectLatestIfMissing: true})
    .then(() => loadChatHistory())
    .catch((error) => {
      renderEmptyChat();
      toast(error.message);
    });
}
