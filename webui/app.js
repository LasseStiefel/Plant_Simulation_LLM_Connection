const bodyEl = document.body;
const messagesEl = document.getElementById("messages");
const parameterListEl = document.getElementById("parameter-list");
const composerEl = document.getElementById("composer");
const inputEl = document.getElementById("message-input");
const sendButtonEl = document.getElementById("send-button");
const statusTextEl = document.getElementById("status-text");
const variablesToggleEl = document.getElementById("variables-toggle");
const variablesDrawerEl = document.getElementById("variables-drawer");
const drawerBackdropEl = document.getElementById("drawer-backdrop");
const closeDrawerEl = document.getElementById("close-drawer");

let currentState = {
  history: [],
  pending_mapping: {},
};

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function setDrawerOpen(isOpen) {
  bodyEl.classList.toggle("drawer-open", isOpen);
  variablesToggleEl.setAttribute("aria-expanded", String(isOpen));
  variablesDrawerEl.setAttribute("aria-hidden", String(!isOpen));
  drawerBackdropEl.hidden = !isOpen;
}

function updateLayout(history) {
  bodyEl.classList.toggle("is-empty", history.length === 0);
}

function renderMessages(history) {
  updateLayout(history);

  if (!history || history.length === 0) {
    messagesEl.innerHTML = "";
    return;
  }

  messagesEl.innerHTML = history
    .map((message) => {
      const roleClass =
        message.role === "user" ? "message-user" : "message-assistant";
      return `
        <div class="message ${roleClass}">
          <div class="message-bubble">${escapeHtml(message.content)}</div>
        </div>
      `;
    })
    .join("");

  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderPendingMapping(pendingMapping) {
  const entries = Object.entries(pendingMapping || {});
  if (entries.length === 0) {
    parameterListEl.innerHTML = `
      <p class="empty-state">No variables are loaded.</p>
    `;
    return;
  }

  parameterListEl.innerHTML = entries
    .sort(([leftName], [rightName]) => leftName.localeCompare(rightName))
    .map(([name, definition]) => {
      const value = definition?.value ?? "N/A";
      const description = definition?.description ?? "";
      const format = definition?.format ?? "";
      return `
        <article class="parameter-card">
          <h3>${escapeHtml(name)}</h3>
          <p class="parameter-value">${escapeHtml(String(value))}</p>
          <p class="parameter-description">${escapeHtml(description)}</p>
          <p class="parameter-format">Format: ${escapeHtml(format)}</p>
        </article>
      `;
    })
    .join("");
}

function renderState(state) {
  currentState = state;
  renderMessages(state.history || []);
  renderPendingMapping(state.pending_mapping || {});
}

function setBusy(isBusy, label) {
  inputEl.disabled = isBusy;
  sendButtonEl.disabled = isBusy;
  statusTextEl.textContent = label;
}

function autosizeTextarea() {
  inputEl.style.height = "0px";
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 220)}px`;
}

function renderTemporaryConversation(message) {
  const optimisticHistory = [
    ...(currentState.history || []),
    { role: "user", content: message },
    { role: "assistant", content: "Thinking..." },
  ];
  renderMessages(optimisticHistory);
}

async function loadState() {
  setBusy(true, "Loading...");
  try {
    const response = await fetch("/api/state");
    if (!response.ok) {
      throw new Error("Failed to load state.");
    }

    const state = await response.json();
    renderState(state);
    setBusy(false, "Ready");
  } catch (error) {
    renderState({
      history: [
        {
          role: "assistant",
          content: `The UI could not load the current state: ${error.message}`,
        },
      ],
      pending_mapping: {},
    });
    setBusy(false, "Unable to load state");
  }
}

async function sendMessage(message) {
  renderTemporaryConversation(message);
  setBusy(true, "Thinking...");

  try {
    const response = await fetch("/api/message", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Message failed.");
    }

    renderState(payload.state);
    if (payload.should_exit) {
      setBusy(true, "Session ended");
      return;
    }

    setBusy(false, payload.ran_simulation ? "Simulation complete" : "Ready");
  } catch (error) {
    renderState({
      history: [
        ...(currentState.history || []),
        {
          role: "assistant",
          content: `Something went wrong while sending the message: ${error.message}`,
        },
      ],
      pending_mapping: currentState.pending_mapping || {},
    });
    setBusy(false, "Error");
  }
}

composerEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = inputEl.value.trim();
  if (!message) {
    return;
  }

  inputEl.value = "";
  autosizeTextarea();
  await sendMessage(message);
});

inputEl.addEventListener("input", autosizeTextarea);

inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composerEl.requestSubmit();
  }
});

variablesToggleEl.addEventListener("click", () => {
  setDrawerOpen(!bodyEl.classList.contains("drawer-open"));
});

closeDrawerEl.addEventListener("click", () => {
  setDrawerOpen(false);
});

drawerBackdropEl.addEventListener("click", () => {
  setDrawerOpen(false);
});

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setDrawerOpen(false);
  }
});

autosizeTextarea();
loadState();
