/**
 * <learning-assistant-widget api-base="http://localhost:8000">
 *
 * Embeddable AI Learning Assistant widget. Vanilla JS Web Component, no
 * build step, no framework — see docs/architecture.md for why.
 *
 * Public API (for a host page, e.g. web/demo/index.html):
 *   widget.open()
 *   widget.close()
 *   widget.toggle()
 *
 * Consumes POST {api-base}/v1/query/stream via fetch() + a manually-parsed
 * ReadableStream (not the native EventSource, which cannot send a POST body
 * — see docs/architecture.md for that decision).
 *
 * Security: nothing coming from the API (answer text, citation fields, error
 * messages) is ever inserted via innerHTML. Every piece of API-provided
 * content is set via textContent / DOM API calls only.
 */

const TEMPLATE = document.createElement("template");
TEMPLATE.innerHTML = `
  <style>
    :host {
      all: initial;
      font-family: system-ui, -apple-system, sans-serif;
      position: fixed;
      top: 0;
      right: 0;
      height: 100%;
      z-index: 2147483000;
    }

    .panel {
      box-sizing: border-box;
      height: 100%;
      width: min(380px, 100vw);
      background: #ffffff;
      border-left: 1px solid #d8dde3;
      box-shadow: -2px 0 12px rgba(0, 0, 0, 0.12);
      display: flex;
      flex-direction: column;
      transform: translateX(100%);
      transition: transform 0.2s ease-out;
    }

    :host([open]) .panel {
      transform: translateX(0);
    }

    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      background: #1f2937;
      color: #fff;
      flex: 0 0 auto;
    }

    .header h2 {
      margin: 0;
      font-size: 15px;
      font-weight: 600;
    }

    .close-btn,
    .fab {
      cursor: pointer;
      border: none;
      background: transparent;
      color: inherit;
      font-size: 18px;
      line-height: 1;
      padding: 4px 8px;
      border-radius: 6px;
    }

    .close-btn:hover {
      background: rgba(255, 255, 255, 0.15);
    }

    .fab {
      position: fixed;
      bottom: 20px;
      right: 20px;
      width: 52px;
      height: 52px;
      border-radius: 50%;
      background: #1f2937;
      color: #fff;
      font-size: 22px;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
      display: flex;
      align-items: center;
      justify-content: center;
    }

    :host([open]) .fab {
      display: none;
    }

    .history {
      flex: 1 1 auto;
      overflow-y: auto;
      padding: 12px 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .msg {
      max-width: 90%;
      padding: 8px 12px;
      border-radius: 10px;
      font-size: 14px;
      line-height: 1.4;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .msg.user {
      align-self: flex-end;
      background: #2563eb;
      color: #fff;
    }

    .msg.assistant {
      align-self: flex-start;
      background: #f1f3f5;
      color: #111827;
    }

    .msg.error {
      align-self: stretch;
      background: #fee2e2;
      color: #991b1b;
    }

    .citations {
      margin-top: 6px;
      font-size: 12px;
      color: #4b5563;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .citation {
      border-top: 1px solid #e5e7eb;
      padding-top: 4px;
    }

    .loading {
      align-self: flex-start;
      font-size: 13px;
      color: #6b7280;
      font-style: italic;
    }

    .composer {
      flex: 0 0 auto;
      display: flex;
      gap: 8px;
      padding: 12px 16px;
      border-top: 1px solid #e5e7eb;
    }

    textarea {
      flex: 1 1 auto;
      resize: none;
      height: 40px;
      font: inherit;
      font-size: 14px;
      padding: 8px;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      box-sizing: border-box;
    }

    button.send {
      flex: 0 0 auto;
      background: #2563eb;
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 0 16px;
      font-size: 14px;
      cursor: pointer;
    }

    button.send:disabled {
      background: #93c5fd;
      cursor: not-allowed;
    }
  </style>

  <button class="fab" type="button" part="fab" aria-label="Abrir el tutor">💬</button>

  <div class="panel">
    <div class="header">
      <h2>Tutor</h2>
      <button class="close-btn" type="button" aria-label="Cerrar">✕</button>
    </div>
    <div class="history"></div>
    <form class="composer">
      <textarea placeholder="Escribe tu pregunta..." required></textarea>
      <button class="send" type="submit">Enviar</button>
    </form>
  </div>
`;

class LearningAssistantWidget extends HTMLElement {
  static get observedAttributes() {
    return ["api-base"];
  }

  constructor() {
    super();
    this._shadow = this.attachShadow({ mode: "open" });
    this._shadow.appendChild(TEMPLATE.content.cloneNode(true));

    this._historyEl = this._shadow.querySelector(".history");
    this._formEl = this._shadow.querySelector(".composer");
    this._textareaEl = this._shadow.querySelector("textarea");
    this._sendBtnEl = this._shadow.querySelector("button.send");

    this._shadow.querySelector(".fab").addEventListener("click", () => this.open());
    this._shadow.querySelector(".close-btn").addEventListener("click", () => this.close());
    this._formEl.addEventListener("submit", (event) => this._onSubmit(event));
  }

  get apiBase() {
    return this.getAttribute("api-base") || "";
  }

  open() {
    this.setAttribute("open", "");
  }

  close() {
    this.removeAttribute("open");
  }

  toggle() {
    if (this.hasAttribute("open")) {
      this.close();
    } else {
      this.open();
    }
  }

  async _onSubmit(event) {
    event.preventDefault();
    const question = this._textareaEl.value.trim();
    if (!question) {
      return;
    }

    this._textareaEl.value = "";
    this._appendUserMessage(question);
    this._setBusy(true);

    const assistantBubble = this._appendAssistantMessage();
    const loadingEl = this._appendLoading();

    try {
      await this._streamAnswer(question, assistantBubble, loadingEl);
    } catch {
      loadingEl.remove();
      this._appendError("No se pudo obtener una respuesta. Intenta de nuevo.");
    } finally {
      this._setBusy(false);
    }
  }

  async _streamAnswer(question, assistantBubble, loadingEl) {
    const response = await fetch(`${this.apiBase}/v1/query/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (!response.ok || !response.body) {
      loadingEl.remove();
      this._appendError(await this._describeErrorResponse(response));
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let firstToken = true;

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        this._handleSseEvent(rawEvent, assistantBubble, () => {
          if (firstToken) {
            loadingEl.remove();
            firstToken = false;
          }
        });
        boundary = buffer.indexOf("\n\n");
      }
    }
  }

  async _describeErrorResponse(response) {
    if (response.status === 422) {
      try {
        const body = await response.json();
        const firstDetail = Array.isArray(body.detail) ? body.detail[0] : undefined;
        if (firstDetail && typeof firstDetail.msg === "string") {
          return `Pregunta inválida: ${firstDetail.msg}`;
        }
      } catch {
        // fall through to the generic message below
      }
      return "La pregunta no es válida (revisa su longitud).";
    }
    return `Error del servidor (${response.status}).`;
  }

  _handleSseEvent(rawEvent, assistantBubble, onFirstToken) {
    let eventType = "message";
    let dataLine = "";
    for (const line of rawEvent.split("\n")) {
      if (line.startsWith("event:")) {
        eventType = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLine += line.slice("data:".length).trim();
      }
    }
    if (!dataLine) {
      return;
    }

    let payload;
    try {
      payload = JSON.parse(dataLine);
    } catch {
      return;
    }

    if (eventType === "token" && typeof payload.text === "string") {
      onFirstToken();
      assistantBubble.appendChild(document.createTextNode(payload.text));
    } else if (eventType === "citations" && Array.isArray(payload.citations)) {
      this._renderCitations(assistantBubble, payload.citations);
    } else if (eventType === "error") {
      onFirstToken();
      this._appendError("La respuesta se interrumpió inesperadamente.");
    }
  }

  _renderCitations(assistantBubble, citations) {
    if (citations.length === 0) {
      return;
    }
    const list = document.createElement("div");
    list.className = "citations";
    for (const citation of citations) {
      const row = document.createElement("div");
      row.className = "citation";
      row.textContent = `Fuente: ${citation.source}, página ${citation.page}`;
      list.appendChild(row);
    }
    assistantBubble.appendChild(list);
  }

  _appendUserMessage(text) {
    const el = document.createElement("div");
    el.className = "msg user";
    el.textContent = text;
    this._historyEl.appendChild(el);
    this._scrollToBottom();
  }

  _appendAssistantMessage() {
    const el = document.createElement("div");
    el.className = "msg assistant";
    this._historyEl.appendChild(el);
    this._scrollToBottom();
    return el;
  }

  _appendLoading() {
    const el = document.createElement("div");
    el.className = "loading";
    el.textContent = "Pensando...";
    this._historyEl.appendChild(el);
    this._scrollToBottom();
    return el;
  }

  _appendError(message) {
    const el = document.createElement("div");
    el.className = "msg error";
    el.textContent = message;
    this._historyEl.appendChild(el);
    this._scrollToBottom();
  }

  _setBusy(busy) {
    this._sendBtnEl.disabled = busy;
    this._textareaEl.disabled = busy;
  }

  _scrollToBottom() {
    this._historyEl.scrollTop = this._historyEl.scrollHeight;
  }
}

customElements.define("learning-assistant-widget", LearningAssistantWidget);
