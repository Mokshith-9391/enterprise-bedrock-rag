(() => {
  const cfg = window.APP_CONFIG || {};
  const $ = (id) => document.getElementById(id);
  let sessionId = null;
  let busy = false;

  // ---------------------------------------------------------------- API

  async function api(path, options = {}) {
    const token = await Auth.idToken();
    if (!token) {
      showSignedOut("Your session ended. Sign in again.");
      throw new Error("signed out");
    }
    const resp = await fetch(cfg.apiUrl + path, {
      ...options,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) },
    });
    let body = {};
    try {
      body = await resp.json();
    } catch {
      /* empty body */
    }
    if (resp.status === 401) {
      showSignedOut("Your session ended. Sign in again.");
      throw new Error("unauthorised");
    }
    if (!resp.ok) {
      const err = new Error(body.error || `Request failed (${resp.status}).`);
      err.status = resp.status;
      throw err;
    }
    return body;
  }

  // ---------------------------------------------------------------- rendering

  const escapeHtml = (s) =>
    s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // Small, safe formatter: paragraphs, bullet/numbered lists, **bold**, [n] citation markers.
  function formatAnswer(text, exchangeId) {
    const inline = (line) =>
      escapeHtml(line)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\[(\d{1,2})\]/g, (_, n) => `<button class="cite" data-n="${n}" data-x="${exchangeId}" aria-label="Source ${n}">${n}</button>`);

    const out = [];
    let list = null;
    for (const raw of text.split("\n")) {
      const line = raw.trim();
      const bullet = line.match(/^[-*•]\s+(.*)/);
      const numbered = line.match(/^\d+[.)]\s+(.*)/);
      if (bullet || numbered) {
        const type = bullet ? "ul" : "ol";
        if (!list || list.type !== type) {
          if (list) out.push(`</${list.type}>`);
          out.push(`<${type}>`);
          list = { type };
        }
        out.push(`<li>${inline((bullet || numbered)[1])}</li>`);
        continue;
      }
      if (list) {
        out.push(`</${list.type}>`);
        list = null;
      }
      if (line) out.push(`<p>${inline(line)}</p>`);
    }
    if (list) out.push(`</${list.type}>`);
    return out.join("");
  }

  function renderSources(sources, exchangeId) {
    if (!sources || !sources.length) return "";
    const items = sources
      .map((s) => {
        const title = s.url
          ? `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.title)}</a>`
          : escapeHtml(s.title);
        const meta = [s.department ? s.department.toUpperCase() : null, s.page ? `page ${s.page}` : null]
          .filter(Boolean)
          .join(", ");
        return `<li class="source" id="src-${exchangeId}-${s.n}">
          <span class="source-n">${s.n}</span>
          <div>
            <div class="source-title">${title}</div>
            ${meta ? `<div class="source-meta">${escapeHtml(meta)}</div>` : ""}
            ${s.snippet ? `<div class="source-snippet">${escapeHtml(s.snippet)}</div>` : ""}
          </div>
        </li>`;
      })
      .join("");
    return `<ol class="sources" aria-label="Sources">${items}</ol>`;
  }

  function addExchange(question) {
    $("welcome")?.remove();
    const id = "x" + Date.now();
    const el = document.createElement("article");
    el.className = "exchange";
    el.id = id;
    el.innerHTML = `<p class="question">${escapeHtml(question)}</p><div class="answer pending">Searching your documents…</div>`;
    $("thread").appendChild(el);
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    return el;
  }

  function fillExchange(el, result) {
    const answer = el.querySelector(".answer");
    answer.classList.remove("pending");
    if (!result.grounded) answer.classList.add("not-found");
    answer.innerHTML = formatAnswer(result.answer || "", el.id) + renderSources(result.sources, el.id);

    if (result.message_id) {
      const actions = document.createElement("div");
      actions.className = "actions";
      actions.innerHTML = `<span>Was this helpful?</span>
        <button data-rating="up" aria-pressed="false">Yes</button>
        <button data-rating="down" aria-pressed="false">No</button>`;
      actions.addEventListener("click", async (e) => {
        const btn = e.target.closest("button[data-rating]");
        if (!btn) return;
        actions.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
        try {
          await api("/feedback", {
            method: "POST",
            body: JSON.stringify({ message_id: result.message_id, rating: btn.dataset.rating }),
          });
          actions.querySelector("span").textContent = "Thanks, feedback saved.";
        } catch (err) {
          actions.querySelector("span").textContent = err.message;
        }
      });
      el.appendChild(actions);
    }
  }

  // Clicking an amber marker highlights its source.
  document.addEventListener("click", (e) => {
    const cite = e.target.closest(".cite");
    if (!cite) return;
    const target = $(`src-${cite.dataset.x}-${cite.dataset.n}`);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "nearest" });
    target.classList.add("flash");
    setTimeout(() => target.classList.remove("flash"), 1400);
  });

  // ---------------------------------------------------------------- actions

  async function ask(question) {
    if (busy) return;
    question = question.trim();
    $("ask-error").textContent = "";
    if (!question) {
      $("ask-error").textContent = "Enter a question first.";
      return;
    }
    busy = true;
    $("ask-btn").disabled = true;
    $("question").value = "";
    const el = addExchange(question);
    try {
      const result = await api("/ask", { method: "POST", body: JSON.stringify({ question, session_id: sessionId }) });
      sessionId = result.session_id || sessionId;
      fillExchange(el, result);
      loadHistory();
    } catch (err) {
      const answer = el.querySelector(".answer");
      answer.classList.remove("pending");
      answer.classList.add("not-found");
      answer.textContent = err.message;
    } finally {
      busy = false;
      $("ask-btn").disabled = false;
      $("question").focus();
    }
  }

  async function loadHistory() {
    try {
      const { items } = await api("/history");
      const list = $("history-list");
      list.innerHTML = "";
      $("history-empty").hidden = items.length > 0;
      for (const item of items) {
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.textContent = item.question;
        btn.title = new Date(item.created_at).toLocaleString();
        btn.addEventListener("click", () => {
          const el = addExchange(item.question);
          fillExchange(el, { ...item, grounded: (item.sources || []).length > 0, message_id: null });
        });
        li.appendChild(btn);
        list.appendChild(li);
      }
    } catch {
      /* history is a convenience; ignore failures */
    }
  }

  async function syncDocuments() {
    const btn = $("sync-btn");
    btn.disabled = true;
    try {
      const out = await api("/admin/sync", { method: "POST", body: "{}" });
      btn.textContent = `Sync ${out.status.toLowerCase()}`;
    } catch (err) {
      btn.textContent = err.status === 409 ? "Sync already running" : "Sync failed";
    } finally {
      setTimeout(() => {
        btn.textContent = "Sync documents";
        btn.disabled = false;
      }, 4000);
    }
  }

  // ---------------------------------------------------------------- screens

  function showSignedOut(message = "") {
    $("app").hidden = true;
    $("account").hidden = true;
    $("signed-out").hidden = false;
    $("login-error").textContent = message;
  }

  function showApp() {
    const user = Auth.user();
    $("signed-out").hidden = true;
    $("app").hidden = false;
    $("account").hidden = false;
    $("email").textContent = user.email;
    $("groups").innerHTML = user.groups.map((g) => `<span class="tag">${escapeHtml(g)}</span>`).join("");
    $("sync-btn").hidden = !user.groups.includes("admin");
    loadHistory();
    $("question").focus();
  }

  // ---------------------------------------------------------------- wiring

  $("app-name").textContent = cfg.appName || "Company knowledge assistant";
  document.title = cfg.appName || document.title;
  $("login-btn").addEventListener("click", () => Auth.login());
  $("logout-btn").addEventListener("click", () => Auth.logout());
  $("sync-btn").addEventListener("click", syncDocuments);
  $("new-chat").addEventListener("click", () => {
    sessionId = null;
    $("thread").innerHTML = "";
    $("question").focus();
  });
  $("ask-form").addEventListener("submit", (e) => {
    e.preventDefault();
    ask($("question").value);
  });
  $("question").addEventListener("input", () => ($("ask-error").textContent = ""));
  $("question").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      ask($("question").value);
    }
  });
  document.querySelectorAll(".suggestion").forEach((b) => b.addEventListener("click", () => ask(b.textContent)));

  (async () => {
    try {
      await Auth.handleRedirect();
    } catch (err) {
      showSignedOut(err.message);
      return;
    }
    (await Auth.idToken()) ? showApp() : showSignedOut();
  })();
})();
