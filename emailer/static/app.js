"use strict";

const limits = {
  files: 5,
  fileBytes: 8 * 1024 * 1024,
  totalBytes: 12 * 1024 * 1024,
  recipients: 50,
};

const fallbackProviders = [
  {
    id: "gmail",
    name: "Gmail",
    auth_method: "app_password",
    enabled: true,
    guidance: "Use a 16-character app password from a Google Account with 2-Step Verification.",
    help_url: "https://support.google.com/accounts/answer/185833",
  },
  {
    id: "yahoo",
    name: "Yahoo Mail",
    auth_method: "app_password",
    enabled: true,
    guidance: "Create a third-party app password in Yahoo Account Security.",
    help_url: "https://help.yahoo.com/kb/generate-manage-third-party-passwords-sln15241.html",
  },
  {
    id: "outlook",
    name: "Outlook.com",
    auth_method: "oauth2",
    enabled: false,
    guidance: "Microsoft requires Modern Auth/OAuth2 for Outlook.com SMTP.",
    unavailable_reason: "OAuth2 sign-in is planned but is not available in this release.",
    help_url: "https://support.microsoft.com/en-us/office/pop-imap-and-smtp-settings-for-outlook-com-d088b986-291d-42b8-9564-9c414e2aa040",
  },
];

const state = {
  providers: fallbackProviders,
  provider: null,
  files: [],
  sending: false,
  serverAvailable: false,
  idempotencyKey: null,
  statusTimer: null,
};

const elements = {
  form: document.querySelector("#email-form"),
  providers: document.querySelector("#provider-options"),
  guidance: document.querySelector("#provider-guidance"),
  senderName: document.querySelector("#sender-name"),
  senderEmail: document.querySelector("#sender-email"),
  password: document.querySelector("#app-password"),
  togglePassword: document.querySelector("#toggle-password"),
  to: document.querySelector("#to"),
  cc: document.querySelector("#cc"),
  bcc: document.querySelector("#bcc"),
  replyTo: document.querySelector("#reply-to"),
  subject: document.querySelector("#subject"),
  body: document.querySelector("#body"),
  fileInput: document.querySelector("#attachments"),
  addFiles: document.querySelector("#add-files"),
  fileList: document.querySelector("#attachment-list"),
  subjectCount: document.querySelector("#subject-count"),
  bodyCount: document.querySelector("#body-count"),
  reviewButton: document.querySelector("#review-button"),
  dialog: document.querySelector("#confirm-dialog"),
  confirmSend: document.querySelector("#confirm-send"),
  status: document.querySelector("#status-message"),
  connection: document.querySelector("#connection-state"),
  reviewProvider: document.querySelector("#review-provider"),
  reviewFrom: document.querySelector("#review-from"),
  reviewTo: document.querySelector("#review-to"),
  reviewCc: document.querySelector("#review-cc"),
  reviewBcc: document.querySelector("#review-bcc"),
  reviewSubject: document.querySelector("#review-subject"),
  reviewBody: document.querySelector("#review-body"),
  reviewFiles: document.querySelector("#review-files"),
};

const fieldByApiName = {
  provider: elements.providers,
  sender_name: elements.senderName,
  sender_email: elements.senderEmail,
  app_password: elements.password,
  to: elements.to,
  cc: elements.cc,
  bcc: elements.bcc,
  reply_to: elements.replyTo,
  subject: elements.subject,
  body: elements.body,
  attachments: elements.addFiles,
};

function parseAddresses(value) {
  return value
    .split(/[,;\n]+/)
    .map((address) => address.trim())
    .filter(Boolean);
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function showStatus(message, kind = "success", persist = false) {
  window.clearTimeout(state.statusTimer);
  elements.status.textContent = message;
  elements.status.className = `toast ${kind}`;
  elements.status.hidden = false;
  if (!persist) {
    state.statusTimer = window.setTimeout(() => {
      elements.status.hidden = true;
    }, 7000);
  }
}

function setProvider(provider) {
  if (!provider.enabled) {
    showStatus(provider.unavailable_reason || "This provider is not available yet.", "warning");
    return;
  }
  if (state.provider && state.provider.id !== provider.id) resetPassword();
  state.provider = provider;
  document.querySelectorAll(".provider-card").forEach((card) => {
    card.setAttribute("aria-checked", String(card.dataset.provider === provider.id));
    card.tabIndex = card.dataset.provider === provider.id ? 0 : -1;
  });
  elements.guidance.replaceChildren();
  const text = document.createElement("span");
  text.textContent = `${provider.guidance} `;
  const link = document.createElement("a");
  link.href = provider.help_url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "Provider instructions";
  elements.guidance.append(text, link);
}

function resetPassword() {
  elements.password.value = "";
  elements.password.type = "password";
  elements.togglePassword.textContent = "Show";
  elements.togglePassword.setAttribute("aria-label", "Show app password");
  elements.togglePassword.setAttribute("aria-pressed", "false");
}

function renderProviders() {
  elements.providers.replaceChildren();
  state.providers.forEach((provider) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "provider-card";
    button.dataset.provider = provider.id;
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", "false");
    button.setAttribute("aria-disabled", String(!provider.enabled));

    const name = document.createElement("strong");
    name.textContent = provider.name;
    const method = document.createElement("small");
    method.textContent = provider.enabled ? "App password" : "OAuth2 required";
    const check = document.createElement("span");
    check.className = "provider-check";
    check.setAttribute("aria-hidden", "true");
    check.textContent = provider.enabled ? "OK" : "--";
    button.append(name, method, check);
    button.addEventListener("click", () => setProvider(provider));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      const enabled = state.providers.filter((item) => item.enabled);
      const current = enabled.findIndex((item) => item.id === state.provider?.id);
      const direction = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1;
      const next = enabled[(current + direction + enabled.length) % enabled.length];
      setProvider(next);
      elements.providers.querySelector(`[data-provider="${next.id}"]`).focus();
    });
    elements.providers.append(button);
  });
  setProvider(state.providers.find((provider) => provider.enabled) || state.providers[0]);
}

async function loadProviders() {
  try {
    const response = await fetch("/api/providers", { cache: "no-store" });
    if (!response.ok) throw new Error("Provider list unavailable");
    const data = await response.json();
    if (Array.isArray(data.providers) && data.providers.length) {
      state.providers = data.providers;
    }
    state.serverAvailable = true;
  } catch {
    state.serverAvailable = false;
    showStatus("Using the built-in provider list. The server may be offline.", "warning");
  }
  renderProviders();
  updateConnectionState();
}

function renderFiles() {
  elements.fileList.replaceChildren();
  state.files.forEach((file, index) => {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${file.name} (${formatBytes(file.size)})`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${file.name}`);
    remove.addEventListener("click", () => {
      state.files.splice(index, 1);
      renderFiles();
    });
    item.append(label, remove);
    elements.fileList.append(item);
  });
}

function addFiles(files) {
  const candidates = [...state.files, ...Array.from(files)];
  if (candidates.length > limits.files) {
    showStatus(`Attach no more than ${limits.files} files.`, "error");
    return;
  }
  const oversized = candidates.find((file) => file.size > limits.fileBytes);
  if (oversized) {
    showStatus(`${oversized.name} is larger than 8 MB.`, "error");
    return;
  }
  const total = candidates.reduce((sum, file) => sum + file.size, 0);
  if (total > limits.totalBytes) {
    showStatus("Attachments must total 12 MB or less.", "error");
    return;
  }
  state.files = candidates;
  renderFiles();
}

function validateRecipients() {
  const fields = [elements.to, elements.cc, elements.bcc];
  fields.forEach((field) => field.setCustomValidity(""));
  const to = parseAddresses(elements.to.value);
  const all = fields.flatMap((field) => parseAddresses(field.value));
  if (!to.length) {
    elements.to.setCustomValidity("Add at least one recipient.");
    return false;
  }
  if (all.length > limits.recipients) {
    elements.to.setCustomValidity(`Use no more than ${limits.recipients} recipients.`);
    return false;
  }
  const simpleEmail = /^[^\s@]+@[^\s@]+$/;
  const invalid = all.find((address) => !simpleEmail.test(address));
  if (invalid) {
    const field = fields.find((candidate) => parseAddresses(candidate.value).includes(invalid));
    field.setCustomValidity(`Check this address: ${invalid}`);
    return false;
  }
  return true;
}

function validateRequiredText() {
  const required = [elements.senderEmail, elements.password, elements.subject, elements.body];
  required.forEach((field) => field.setCustomValidity(""));
  for (const field of required) {
    if (!field.value.trim()) {
      field.setCustomValidity("This field is required.");
      return false;
    }
  }
  return true;
}

function newIdempotencyKey() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function prepareReview() {
  if (!state.provider) {
    showStatus("Select an available provider.", "error");
    return;
  }
  const recipientsValid = validateRecipients();
  const requiredTextValid = validateRequiredText();
  if (!recipientsValid || !requiredTextValid) {
    elements.form.reportValidity();
    return;
  }
  if (!elements.form.reportValidity()) return;

  const to = parseAddresses(elements.to.value);
  const cc = parseAddresses(elements.cc.value);
  const bcc = parseAddresses(elements.bcc.value);
  state.idempotencyKey = newIdempotencyKey();
  elements.reviewProvider.textContent = state.provider.name;
  elements.reviewFrom.textContent = elements.senderName.value.trim()
    ? `${elements.senderName.value.trim()} <${elements.senderEmail.value.trim()}>`
    : elements.senderEmail.value.trim();
  elements.reviewTo.textContent = to.join(", ");
  elements.reviewCc.textContent = cc.join(", ") || "None";
  elements.reviewBcc.textContent = bcc.join(", ") || "None";
  elements.reviewSubject.textContent = elements.subject.value.trim();
  elements.reviewBody.textContent = elements.body.value;
  elements.reviewFiles.textContent = state.files.length
    ? state.files.map((file) => `${file.name} (${formatBytes(file.size)})`).join(", ")
    : "None";
  checkServerHealth();
  elements.dialog.showModal();
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      const result = String(reader.result);
      resolve(result.slice(result.indexOf(",") + 1));
    });
    reader.addEventListener("error", () => reject(new Error(`Could not read ${file.name}.`)));
    reader.readAsDataURL(file);
  });
}

async function sendMessage() {
  if (state.sending) return;
  if (!state.serverAvailable) {
    showStatus("The local email service is unavailable. Start it before sending.", "error");
    return;
  }
  state.sending = true;
  elements.confirmSend.disabled = true;
  elements.confirmSend.textContent = "Sending...";

  let payload;
  let dispatched = false;
  let definitiveResponse = false;
  try {
    const attachments = await Promise.all(
      state.files.map(async (file) => ({
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        content: await fileToBase64(file),
      })),
    );
    payload = {
      provider: state.provider.id,
      sender_name: elements.senderName.value.trim(),
      sender_email: elements.senderEmail.value.trim(),
      app_password: elements.password.value,
      to: parseAddresses(elements.to.value),
      cc: parseAddresses(elements.cc.value),
      bcc: parseAddresses(elements.bcc.value),
      reply_to: elements.replyTo.value.trim(),
      subject: elements.subject.value.trim(),
      body: elements.body.value,
      attachments,
    };

    let response;
    try {
      dispatched = true;
      response = await fetch("/api/send", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Emailer-Request": "send-message",
          "Idempotency-Key": state.idempotencyKey,
        },
        body: JSON.stringify(payload),
      });
    } finally {
      payload.app_password = "";
      resetPassword();
    }

    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.ok) {
      definitiveResponse = Boolean(data?.error?.message);
      if (data?.error?.field) {
        elements.dialog.close();
        applyFieldError(data.error.field, data.error.message);
      }
      throw new Error(data?.error?.message || "The send request failed.");
    }
    definitiveResponse = true;
    elements.dialog.close();
    const refusedNote = data.refused?.length
      ? ` Refused: ${data.refused.slice(0, 3).join(", ")}${data.refused.length > 3 ? ` and ${data.refused.length - 3} more` : ""}.`
      : "";
    showStatus(`${data.message}${refusedNote}`, data.status === "partial" ? "warning" : "success", true);
  } catch (error) {
    const message = dispatched && !definitiveResponse
      ? "No definitive result was received. Check Sent Mail before trying again."
      : error.message || "The message could not be sent.";
    showStatus(message, "error", true);
    if (dispatched && !definitiveResponse) checkServerHealth();
  } finally {
    if (payload) payload.app_password = "";
    resetPassword();
    state.sending = false;
    elements.confirmSend.textContent = "Confirm and send";
    updateConnectionState();
  }
}

function applyFieldError(fieldName, message) {
  const field = fieldByApiName[fieldName];
  if (!field) return;
  if (typeof field.setCustomValidity === "function") {
    field.setCustomValidity(message);
    field.reportValidity();
  }
  field.focus();
}

async function checkServerHealth() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    state.serverAvailable = response.ok;
  } catch {
    state.serverAvailable = false;
  }
  updateConnectionState();
  return state.serverAvailable;
}

function updateConnectionState() {
  const label = elements.connection.lastElementChild;
  const ready = state.serverAvailable;
  elements.connection.classList.toggle("offline", !ready);
  label.textContent = ready ? "Ready" : "Service unavailable";
  elements.confirmSend.disabled = state.sending || !ready;
}

elements.form.addEventListener("submit", (event) => event.preventDefault());
elements.reviewButton.addEventListener("click", prepareReview);
elements.confirmSend.addEventListener("click", sendMessage);
elements.addFiles.addEventListener("click", () => elements.fileInput.click());
elements.fileInput.addEventListener("change", () => {
  addFiles(elements.fileInput.files);
  elements.fileInput.value = "";
});
elements.togglePassword.addEventListener("click", () => {
  const show = elements.password.type === "password";
  elements.password.type = show ? "text" : "password";
  elements.togglePassword.textContent = show ? "Hide" : "Show";
  elements.togglePassword.setAttribute("aria-label", `${show ? "Hide" : "Show"} app password`);
  elements.togglePassword.setAttribute("aria-pressed", String(show));
});
elements.subject.addEventListener("input", () => {
  elements.subjectCount.textContent = `${elements.subject.value.length} / 200`;
});
elements.body.addEventListener("input", () => {
  elements.bodyCount.textContent = `${elements.body.value.length.toLocaleString()} / 100,000`;
});
document.querySelectorAll("input, textarea").forEach((field) => {
  field.addEventListener("input", () => field.setCustomValidity(""));
});
window.addEventListener("online", checkServerHealth);
window.addEventListener("offline", checkServerHealth);

updateConnectionState();
loadProviders();
window.setInterval(checkServerHealth, 10000);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
