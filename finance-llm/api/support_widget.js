/* Widget de apoio ao cliente do IQ OS.
 *
 * Autocontido e sem dependências: cria um Shadow DOM para não colidir com o CSS
 * do site (CMS, loja ou SPA), fala com a API por `data-api-base` (por omissão
 * `/api`) e mantém a conversa em WebSocket (`/support/ws`) com recurso a
 * pedidos REST quando a ligação cai.
 *
 * Instalação (o snippet do servidor já faz isto):
 *   <script async src="/api/support/widget.js"
 *           data-iqos-support data-api-base="/api"></script>
 */
(function () {
  "use strict";

  if (window.__IQOS_SUPPORT_WIDGET__) return;
  window.__IQOS_SUPPORT_WIDGET__ = true;

  var STORAGE_KEY = "iqos-support-v1";
  var AUTH_KEY = "finance-llm-token";

  var script =
    document.currentScript ||
    document.querySelector("script[data-iqos-support]") ||
    document.querySelector('script[src*="support/widget.js"]');
  var apiBase = (window.__IQOS_SUPPORT_API__ || (script && script.getAttribute("data-api-base")) || "/api")
    .replace(/\/+$/, "");
  if (!apiBase) apiBase = "";
  var wsBase = apiBase;

  var DEFAULT_CONFIG = {
    title: "Apoio ao cliente",
    greeting: "Olá! Em que podemos ajudar?",
    away_message: "Deixe a sua mensagem e respondemos assim que possível.",
    online_message: "Normalmente respondemos em poucos minutos.",
    placeholder: "Escreva a sua mensagem…",
    quick_replies: ["Tenho uma pergunta", "Quero saber mais"],
    ticket_categories: ["Conta", "Faturação", "Dados", "Sugestão", "Outro"],
    business_hours: "Dias úteis, 9h–19h (Lisboa)",
    available: true,
    operators_online: 0,
  };

  var S = {
    visitorId: null,
    token: null,
    sessionId: null,
    profile: { name: "", email: "" },
    config: DEFAULT_CONFIG,
    session: null,
    messages: [],
    open: false,
    unread: 0,
    connected: false,
    typing: false,
    view: "chat",
    busy: false,
    error: "",
    ticketSent: "",
    lastTypingSent: 0,
    lastPage: "",
    formDrafts: {},
    formBusy: {},
  };

  var socket = null;
  var reconnectTimer = null;
  var reconnectDelay = 1000;
  var pingTimer = null;
  var pageTimer = null;
  var typingTimer = null;
  var pollTimer = null;
  var host = null;
  var root = null;
  var refs = {};

  /* --------------------------------------------------------------- estado */
  function readAuthToken() {
    try {
      return window.localStorage.getItem(AUTH_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function load() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      var saved = JSON.parse(raw);
      if (!saved || typeof saved !== "object") return;
      S.visitorId = typeof saved.visitorId === "string" ? saved.visitorId : null;
      S.token = typeof saved.token === "string" ? saved.token : null;
      S.sessionId = typeof saved.sessionId === "string" ? saved.sessionId : null;
      S.profile = {
        name: (saved.profile && saved.profile.name) || "",
        email: (saved.profile && saved.profile.email) || "",
      };
      S.unread = Number(saved.unread) || 0;
    } catch (error) {
      /* armazenamento indisponível */
    }
  }

  function save() {
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          visitorId: S.visitorId,
          token: S.token,
          sessionId: S.sessionId,
          profile: S.profile,
          unread: S.unread,
        }),
      );
    } catch (error) {
      /* modo privado */
    }
  }

  function resetConversation() {
    S.sessionId = null;
    S.session = null;
    S.messages = [];
    S.unread = 0;
    S.view = "chat";
    S.ticketSent = "";
    save();
    render();
  }

  /* ------------------------------------------------------------------ API */
  function api(path, options) {
    var opts = options || {};
    var headers = { Accept: "application/json" };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (S.token) headers["X-Support-Token"] = S.token;
    var authToken = readAuthToken();
    if (authToken) headers.Authorization = "Bearer " + authToken;
    return fetch(apiBase + path, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      credentials: "same-origin",
    }).then(function (response) {
      return response
        .text()
        .then(function (text) {
          var payload = null;
          try {
            payload = text ? JSON.parse(text) : null;
          } catch (error) {
            payload = null;
          }
          if (!response.ok) {
            if (response.status === 401) {
              S.token = null;
              S.sessionId = null;
            }
            var detail = payload && payload.detail ? payload.detail : "Erro " + response.status;
            var failure = new Error(String(detail));
            failure.status = response.status;
            throw failure;
          }
          return payload;
        });
    });
  }

  function pageContext() {
    var nav = window.navigator || {};
    var params = new URLSearchParams(window.location.search);
    var utm = {};
    ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"].forEach(function (key) {
      if (params.get(key)) utm[key] = params.get(key);
    });
    return {
      url: window.location.href,
      path: window.location.pathname,
      title: document.title || "",
      referrer: document.referrer || "",
      landing_url: S.lastPage || window.location.href,
      locale: nav.language || "",
      timezone: (window.Intl && Intl.DateTimeFormat && Intl.DateTimeFormat().resolvedOptions().timeZone) || "",
      screen: { width: window.screen ? window.screen.width : 0, height: window.screen ? window.screen.height : 0 },
      viewport: { width: window.innerWidth || 0, height: window.innerHeight || 0 },
      device: /Mobi|Android|iPhone|iPad/i.test(nav.userAgent || "") ? "mobile" : "desktop",
      utm: utm,
      language: document.documentElement.lang || "",
    };
  }

  function bootstrap() {
    return api("/support/visitors", {
      method: "POST",
      body: { visitor_id: S.visitorId, profile: S.profile, context: pageContext() },
    })
      .then(function (data) {
        S.visitorId = data.visitor_id;
        S.token = data.token;
        if (data.config) S.config = Object.assign({}, DEFAULT_CONFIG, data.config);
        S.lastPage = window.location.href;
        save();
        render();
        return data;
      })
      .catch(function (error) {
        if (error && error.status === 429) return null;
        throw error;
      });
  }

  function startSession() {
    S.busy = true;
    S.error = "";
    render();
    return bootstrap()
      .then(function () {
        return api("/support/sessions", {
          method: "POST",
          body: { profile: S.profile, context: pageContext() },
        });
      })
      .then(function (data) {
        S.session = data.session;
        S.sessionId = data.session.id;
        S.messages = Array.isArray(data.messages) ? data.messages : [];
        if (data.config) S.config = Object.assign({}, DEFAULT_CONFIG, data.config);
        S.view = "chat";
        S.busy = false;
        save();
        connect();
        if (socket && socket.readyState === 1) {
          socket.send(JSON.stringify({ type: "context", session_id: S.sessionId, context: pageContext() }));
        }
        render();
        markRead();
        scrollToEnd();
      })
      .catch(function (error) {
        S.busy = false;
        S.error = error.message || "Não foi possível abrir a conversa.";
        render();
      });
  }

  function refreshSession() {
    if (!S.sessionId) return Promise.resolve();
    return api("/support/sessions/" + encodeURIComponent(S.sessionId))
      .then(function (data) {
        S.session = data.session;
        S.messages = Array.isArray(data.messages) ? data.messages : [];
        if (S.session.status === "closed" && !S.session.rating) {
          S.view = "chat";
        }
        render();
        scrollToEnd();
      })
      .catch(function (error) {
        if (error && (error.status === 403 || error.status === 404)) resetConversation();
      });
  }

  function sendMessage(text) {
    var body = String(text || "").trim();
    if (!body) return;
    if (!S.sessionId) {
      S.profile = Object.assign({}, S.profile);
      S.pendingMessage = body;
      startSession().then(function () {
        var pending = S.pendingMessage;
        S.pendingMessage = "";
        if (pending && S.sessionId) sendMessage(pending);
      });
      return;
    }
    var clientId = "c_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
    var optimistic = {
      id: clientId,
      client_id: clientId,
      session_id: S.sessionId,
      author_type: "visitor",
      author_name: S.profile.name || "Visitante",
      body: body,
      created_at: new Date().toISOString(),
      pending: true,
    };
    S.messages.push(optimistic);
    S.error = "";
    render();
    scrollToEnd();
    var payload = { type: "message", session_id: S.sessionId, body: body, client_id: clientId };
    var sent =
      S.connected && socket && socket.readyState === 1
        ? Promise.resolve(socket.send(JSON.stringify(payload)))
        : api("/support/sessions/" + encodeURIComponent(S.sessionId) + "/messages", {
            method: "POST",
            body: { body: body, client_id: clientId },
          }).then(function (data) {
            if (data && data.message) upsertMessage(data.message);
          });
    sent.catch(function (error) {
      optimistic.failed = true;
      S.error = error.message || "Não foi possível enviar a mensagem.";
      render();
    });
  }

  function openTicket(subject, description, category) {
    if (!S.sessionId) return;
    S.busy = true;
    S.error = "";
    render();
    api("/support/sessions/" + encodeURIComponent(S.sessionId) + "/ticket", {
      method: "POST",
      body: { subject: subject, description: description, category: category, priority: "normal" },
    })
      .then(function (data) {
        S.busy = false;
        S.ticketSent = data.ticket && data.ticket.id ? data.ticket.id : "ok";
        S.view = "chat";
        render();
        return refreshSession();
      })
      .catch(function (error) {
        S.busy = false;
        S.error = error.message || "Não foi possível abrir o ticket.";
        render();
      });
  }

  function rate(value) {
    if (!S.sessionId) return;
    api("/support/sessions/" + encodeURIComponent(S.sessionId) + "/rate", {
      method: "POST",
      body: { rating: value, comment: "" },
    })
      .then(function (data) {
        S.session = data.session;
        render();
      })
      .catch(function (error) {
        S.error = error.message || "Não foi possível registar a avaliação.";
        render();
      });
  }

  function closeConversation() {
    if (!S.sessionId) return;
    var request =
      S.connected && socket && socket.readyState === 1
        ? Promise.resolve(socket.send(JSON.stringify({ type: "close", session_id: S.sessionId })))
        : api("/support/sessions/" + encodeURIComponent(S.sessionId) + "/close", { method: "POST" }).then(function (data) {
            if (data && data.session) S.session = data.session;
            render();
          });
    request.catch(function (error) {
      S.error = error.message || "Não foi possível fechar a conversa.";
      render();
    });
  }

  function markRead() {
    if (!S.sessionId) return;
    if (S.connected && socket && socket.readyState === 1) {
      socket.send(JSON.stringify({ type: "read", session_id: S.sessionId }));
    } else {
      api("/support/sessions/" + encodeURIComponent(S.sessionId) + "/read", { method: "POST" }).catch(function () {
        /* silencioso */
      });
    }
    if (S.session) S.session.unread_visitor = 0;
  }

  /* -------------------------------------------------------------- WebSocket */
  function socketUrl() {
    var base = wsBase;
    var absolute;
    if (/^https?:\/\//i.test(base)) {
      absolute = new URL(base + "/support/ws");
    } else {
      absolute = new URL((base || "") + "/support/ws", window.location.href);
    }
    absolute.protocol = absolute.protocol === "https:" ? "wss:" : "ws:";
    absolute.searchParams.set("role", "visitor");
    absolute.searchParams.set("token", S.token || "");
    if (S.sessionId) absolute.searchParams.set("session_id", S.sessionId);
    return absolute.toString();
  }

  function connect() {
    if (!S.token) return;
    if (socket && (socket.readyState === 0 || socket.readyState === 1)) return;
    clearTimeout(reconnectTimer);
    try {
      socket = new WebSocket(socketUrl());
    } catch (error) {
      scheduleReconnect();
      return;
    }
    socket.onopen = function () {
      S.connected = true;
      reconnectDelay = 1000;
      render();
      clearInterval(pingTimer);
      pingTimer = window.setInterval(function () {
        if (socket && socket.readyState === 1) socket.send(JSON.stringify({ type: "ping" }));
      }, 25000);
      if (S.sessionId) {
        socket.send(JSON.stringify({ type: "context", session_id: S.sessionId, context: pageContext() }));
      }
      markRead();
    };
    socket.onmessage = function (event) {
      var payload = null;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      handleEvent(payload);
    };
    socket.onclose = function () {
      S.connected = false;
      clearInterval(pingTimer);
      render();
      scheduleReconnect();
    };
    socket.onerror = function () {
      if (socket) socket.close();
    };
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    if (!S.open) return;
    reconnectTimer = window.setTimeout(function () {
      reconnectDelay = Math.min(reconnectDelay * 1.6, 15000);
      connect();
    }, reconnectDelay);
  }

  function handleEvent(payload) {
    if (!payload || typeof payload !== "object") return;
    switch (payload.type) {
      case "ready":
        if (payload.session) S.session = payload.session;
        if (Array.isArray(payload.messages) && payload.messages.length) S.messages = payload.messages;
        if (payload.config) S.config = Object.assign({}, DEFAULT_CONFIG, payload.config);
        if (S.session) {
          S.sessionId = S.session.id;
          save();
        }
        render();
        scrollToEnd();
        break;
      case "message.created":
        if (payload.message) {
          upsertMessage(payload.message);
          if (payload.message.author_type !== "visitor") {
            if (S.open) markRead();
            else {
              S.unread += 1;
              save();
            }
          }
        }
        if (payload.session) S.session = payload.session;
        S.typing = false;
        render();
        scrollToEnd();
        break;
      case "session.updated":
      case "session.closed":
        if (payload.session) S.session = payload.session;
        if (payload.type === "session.closed") S.view = "chat";
        render();
        break;
      case "operator.joined":
        if (payload.session) S.session = payload.session;
        render();
        break;
      case "ticket.created":
        if (payload.ticket) S.ticketSent = payload.ticket.id || "ok";
        render();
        break;
      case "form.submitted":
        if (payload.message) {
          upsertMessage(payload.message);
          delete S.formDrafts[payload.message.id];
        }
        if (payload.session) S.session = payload.session;
        render();
        scrollToEnd();
        break;
      case "typing":
        if (payload.actor === "operator") {
          S.typing = true;
          render();
          clearTimeout(typingTimer);
          typingTimer = window.setTimeout(function () {
            S.typing = false;
            render();
          }, 4000);
        }
        break;
      case "presence":
        S.config.operators_online = Number(payload.operators_online) || 0;
        if (S.config.operators_online > 0) S.config.available = true;
        render();
        break;
      case "error":
        S.error = payload.message || "Erro inesperado.";
        render();
        break;
      default:
        break;
    }
  }

  function upsertMessage(message) {
    if (!message || !message.id) return;
    var replaced = false;
    for (var index = 0; index < S.messages.length; index++) {
      var current = S.messages[index];
      if (current.id === message.id || (message.client_id && current.client_id === message.client_id)) {
        S.messages[index] = message;
        replaced = true;
        break;
      }
    }
    if (!replaced) S.messages.push(message);
  }

  /* --------------------------------------------------------------- tracking */
  function trackPage() {
    var href = window.location.href;
    if (!S.token || href === S.lastPage) return;
    S.lastPage = href;
    if (S.sessionId) {
      if (S.connected && socket && socket.readyState === 1) {
        socket.send(JSON.stringify({ type: "context", session_id: S.sessionId, context: pageContext() }));
      } else {
        api("/support/sessions/" + encodeURIComponent(S.sessionId) + "/context", {
          method: "POST",
          body: { context: pageContext() },
        }).catch(function () {
          /* silencioso */
        });
      }
    }
  }

  function installPageTracking() {
    ["pushState", "replaceState"].forEach(function (name) {
      var original = history[name];
      if (typeof original !== "function") return;
      history[name] = function () {
        var result = original.apply(this, arguments);
        trackPage();
        return result;
      };
    });
    window.addEventListener("popstate", trackPage);
    window.addEventListener("hashchange", trackPage);
    pageTimer = window.setInterval(trackPage, 2500);
  }

  /* ---------------------------------------------------------------- render */
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function icon(name) {
    var paths = {
      chat:
        "M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z",
      close: "M18 6 6 18M6 6l12 12",
      send: "m22 2-7 20-4-9-9-4Z M22 2 11 13",
      ticket:
        "M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z M13 5v2 M13 17v2 M13 11v2",
      back: "M19 12H5M12 19l-7-7 7-7",
    };
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", paths[name] || "");
    svg.appendChild(path);
    return svg;
  }

  function relativeTime(value) {
    if (!value) return "";
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    var diff = Math.round((Date.now() - date.getTime()) / 1000);
    if (diff < 60) return "agora";
    if (diff < 3600) return Math.floor(diff / 60) + " min";
    if (diff < 86400) return Math.floor(diff / 3600) + " h";
    return date.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit" });
  }

  function build() {
    host = document.createElement("div");
    host.id = "iqos-support-widget";
    root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;

    var style = document.createElement("style");
    style.textContent = CSS;
    root.appendChild(style);

    var wrap = el("div", "iq-wrap");

    var launcher = el("button", "iq-launcher");
    launcher.type = "button";
    launcher.setAttribute("aria-label", "Abrir o apoio ao cliente");
    launcher.appendChild(icon("chat"));
    var badge = el("span", "iq-badge", "0");
    launcher.appendChild(badge);
    launcher.addEventListener("click", function () {
      if (S.open) {
        setOpen(false);
      } else {
        setOpen(true);
      }
    });
    wrap.appendChild(launcher);

    var panel = el("section", "iq-panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Apoio ao cliente");
    panel.hidden = true;

    var header = el("header", "iq-header");
    var avatar = el("span", "iq-avatar");
    avatar.appendChild(icon("chat"));
    header.appendChild(avatar);
    var heading = el("div", "iq-heading");
    var title = el("p", "iq-title", S.config.title);
    var status = el("p", "iq-status");
    var dot = el("span", "iq-dot");
    var statusText = el("span", null, "A ligar…");
    status.appendChild(dot);
    status.appendChild(statusText);
    heading.appendChild(title);
    heading.appendChild(status);
    header.appendChild(heading);
    var minimize = el("button", "iq-icon-button");
    minimize.type = "button";
    minimize.setAttribute("aria-label", "Minimizar a conversa");
    minimize.appendChild(icon("close"));
    minimize.addEventListener("click", function () {
      setOpen(false);
    });
    header.appendChild(minimize);
    panel.appendChild(header);

    var body = el("div", "iq-body");
    panel.appendChild(body);

    var chatView = el("div", "iq-chat");
    var scroll = el("div", "iq-messages");
    scroll.setAttribute("role", "log");
    scroll.setAttribute("aria-live", "polite");
    chatView.appendChild(scroll);

    var typing = el("p", "iq-typing", "O operador está a escrever…");
    typing.hidden = true;
    chatView.appendChild(typing);

    var startBox = el("div", "iq-start");
    var greeting = el("p", "iq-greeting", S.config.greeting);
    var away = el("p", "iq-away", S.config.away_message);
    var startForm = el("form", "iq-start-form");
    startForm.innerHTML =
      '<label class="iq-field"><span>Nome</span><input name="name" autocomplete="name" maxlength="120" placeholder="O seu nome"></label>' +
      '<label class="iq-field"><span>Email (opcional)</span><input name="email" type="email" autocomplete="email" maxlength="160" placeholder="nome@empresa.pt"></label>';
    var startButton = el("button", "iq-primary", "Iniciar conversa");
    startButton.type = "button";
    startButton.addEventListener("click", function () {
      var name = startForm.elements.name.value.trim();
      var email = startForm.elements.email.value.trim();
      if (name) S.profile.name = name;
      if (email) S.profile.email = email;
      save();
      startSession();
    });
    var quick = el("div", "iq-quick");
    var ticketButtonStart = el("button", "iq-link", "Prefiro abrir um ticket");
    ticketButtonStart.type = "button";
    ticketButtonStart.addEventListener("click", function () {
      if (!S.sessionId) startSession().then(function () {
        if (S.sessionId) {
          S.view = "ticket";
          render();
        }
      });
      else {
        S.view = "ticket";
        render();
      }
    });
    startBox.appendChild(greeting);
    startBox.appendChild(away);
    startBox.appendChild(startForm);
    startBox.appendChild(startButton);
    startBox.appendChild(quick);
    startBox.appendChild(ticketButtonStart);
    chatView.appendChild(startBox);

    var closedBox = el("div", "iq-closed");
    var closedText = el("p", null, "Esta conversa terminou. Obrigado pelo contacto.");
    var stars = el("div", "iq-stars");
    for (var value = 1; value <= 5; value++) {
      (function (rating) {
        var star = el("button", "iq-star", "★");
        star.type = "button";
        star.setAttribute("aria-label", "Avaliar com " + rating + " de 5");
        star.addEventListener("click", function () {
          rate(rating);
        });
        stars.appendChild(star);
      })(value);
    }
    var restart = el("button", "iq-primary", "Nova conversa");
    restart.type = "button";
    restart.addEventListener("click", function () {
      resetConversation();
      startSession();
    });
    closedBox.appendChild(closedText);
    closedBox.appendChild(stars);
    closedBox.appendChild(restart);
    chatView.appendChild(closedBox);

    var composer = el("form", "iq-composer");
    var input = el("textarea", "iq-input");
    input.rows = 1;
    input.maxLength = 4000;
    input.placeholder = S.config.placeholder;
    input.setAttribute("aria-label", "Mensagem");
    var send = el("button", "iq-send");
    send.type = "submit";
    send.setAttribute("aria-label", "Enviar mensagem");
    send.appendChild(icon("send"));
    composer.appendChild(input);
    composer.appendChild(send);
    chatView.appendChild(composer);

    var footer = el("div", "iq-footer");
    var ticketLink = el("button", "iq-link", "Abrir ticket");
    ticketLink.type = "button";
    ticketLink.addEventListener("click", function () {
      S.view = "ticket";
      render();
    });
    var endLink = el("button", "iq-link", "Terminar conversa");
    endLink.type = "button";
    endLink.addEventListener("click", closeConversation);
    footer.appendChild(ticketLink);
    footer.appendChild(endLink);
    chatView.appendChild(footer);

    body.appendChild(chatView);

    var ticketView = el("div", "iq-ticket-view");
    var ticketHeader = el("div", "iq-ticket-head");
    var back = el("button", "iq-icon-button");
    back.type = "button";
    back.setAttribute("aria-label", "Voltar à conversa");
    back.appendChild(icon("back"));
    back.addEventListener("click", function () {
      S.view = "chat";
      render();
    });
    ticketHeader.appendChild(back);
    ticketHeader.appendChild(el("p", "iq-ticket-title", "Abrir ticket"));
    ticketView.appendChild(ticketHeader);
    var ticketForm = el("form", "iq-ticket-form");
    ticketForm.innerHTML =
      '<label class="iq-field"><span>Assunto</span><input name="subject" maxlength="200" required placeholder="Resumo do problema"></label>' +
      '<label class="iq-field"><span>Categoria</span><select name="category"></select></label>' +
      '<label class="iq-field"><span>Descrição</span><textarea name="description" rows="5" maxlength="8000" placeholder="Descreva o que se passa, com o máximo de detalhe possível."></textarea></label>';
    var ticketSubmit = el("button", "iq-primary", "Enviar ticket");
    ticketSubmit.type = "submit";
    ticketForm.appendChild(ticketSubmit);
    ticketView.appendChild(ticketForm);
    body.appendChild(ticketView);

    var error = el("p", "iq-error");
    error.hidden = true;
    body.appendChild(error);

    panel.appendChild(body);
    wrap.appendChild(panel);
    root.appendChild(wrap);

    refs = {
      wrap: wrap,
      launcher: launcher,
      badge: badge,
      panel: panel,
      title: title,
      dot: dot,
      statusText: statusText,
      body: body,
      chatView: chatView,
      scroll: scroll,
      typing: typing,
      startBox: startBox,
      greeting: greeting,
      away: away,
      startForm: startForm,
      startButton: startButton,
      quick: quick,
      closedBox: closedBox,
      composer: composer,
      input: input,
      send: send,
      footer: footer,
      ticketView: ticketView,
      ticketForm: ticketForm,
      error: error,
      stars: stars,
    };

    startForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var name = startForm.elements.name.value.trim();
      var email = startForm.elements.email.value.trim();
      if (name) S.profile.name = name;
      if (email) S.profile.email = email;
      save();
      startSession();
    });

    quick.addEventListener("click", function (event) {
      var chip = event.target.closest(".iq-chip");
      if (!chip) return;
      input.value = chip.textContent || "";
      input.focus();
    });

    composer.addEventListener("submit", function (event) {
      event.preventDefault();
      var text = input.value;
      input.value = "";
      autoGrow();
      sendMessage(text);
    });

    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        composer.dispatchEvent(new Event("submit", { cancelable: true }));
      }
    });

    input.addEventListener("input", function () {
      autoGrow();
      var now = Date.now();
      if (S.connected && socket && socket.readyState === 1 && S.sessionId && now - S.lastTypingSent > 2000) {
        S.lastTypingSent = now;
        socket.send(JSON.stringify({ type: "typing", session_id: S.sessionId }));
      }
    });

    ticketForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var subject = ticketForm.elements.subject.value.trim();
      if (subject.length < 3) {
        S.error = "Indique um assunto com pelo menos 3 caracteres.";
        render();
        return;
      }
      openTicket(
        subject,
        ticketForm.elements.description.value.trim(),
        ticketForm.elements.category.value,
      );
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && S.open) setOpen(false);
    });

    document.body.appendChild(host);
    render();
  }

  function autoGrow() {
    if (!refs.input) return;
    refs.input.style.height = "auto";
    refs.input.style.height = Math.min(refs.input.scrollHeight, 120) + "px";
  }

  function setOpen(open) {
    S.open = !!open;
    if (S.open) {
      S.unread = 0;
      S.error = "";
      save();
      if (!S.token) {
        bootstrap().then(connect).catch(function (error) {
          S.error = error.message || "Não foi possível contactar o apoio.";
          render();
        });
      } else {
        connect();
      }
      if (S.sessionId) refreshSession().then(markRead);
      render();
      scrollToEnd();
      if (S.session && refs.input) {
        window.setTimeout(function () {
          refs.input.focus();
        }, 80);
      }
    } else {
      clearTimeout(reconnectTimer);
    }
    render();
  }

  function render() {
    if (!refs.panel) return;
    refs.panel.hidden = !S.open;
    refs.launcher.setAttribute("aria-expanded", S.open ? "true" : "false");
    refs.badge.textContent = S.unread > 99 ? "99+" : String(S.unread);
    refs.badge.hidden = !S.unread;
    refs.title.textContent = S.config.title || DEFAULT_CONFIG.title;

    var online = Number(S.config.operators_online) > 0;
    var available = S.config.available !== false;
    refs.dot.className = "iq-dot" + (online ? " is-online" : available ? " is-hours" : " is-offline");
    if (S.session && S.session.assigned_operator_name) {
      refs.statusText.textContent = "Com " + S.session.assigned_operator_name;
    } else if (online) {
      refs.statusText.textContent = "Online · respondemos em minutos";
    } else if (available) {
      refs.statusText.textContent = "Horário de atendimento · " + (S.config.business_hours || "");
    } else {
      refs.statusText.textContent = "Fora de horas · deixe a mensagem";
    }

    var hasSession = !!S.sessionId && !!S.session;
    var isClosed = !!(S.session && S.session.status === "closed");
    refs.scroll.style.display = hasSession ? "flex" : "none";
    refs.startBox.hidden = hasSession;
    refs.composer.hidden = !hasSession || isClosed;
    refs.footer.hidden = !hasSession || isClosed;
    refs.closedBox.hidden = !hasSession || !isClosed;
    refs.stars.hidden = !isClosed || !!S.session.rating;
    refs.typing.hidden = !S.typing;
    refs.greeting.textContent = S.config.greeting || DEFAULT_CONFIG.greeting;
    refs.away.textContent = online
      ? S.config.online_message || DEFAULT_CONFIG.online_message
      : S.config.away_message || DEFAULT_CONFIG.away_message;
    refs.input.placeholder = S.config.placeholder || DEFAULT_CONFIG.placeholder;
    refs.startButton.disabled = S.busy;
    refs.startButton.textContent = S.busy ? "A abrir…" : "Iniciar conversa";
    refs.send.disabled = S.busy;

    if (S.profile.name && refs.startForm.elements.name) refs.startForm.elements.name.value = S.profile.name;
    if (S.profile.email && refs.startForm.elements.email) refs.startForm.elements.email.value = S.profile.email;

    refs.chatView.hidden = S.view !== "chat";
    refs.ticketView.hidden = S.view !== "ticket";

    var categories = S.config.ticket_categories || DEFAULT_CONFIG.ticket_categories;
    var select = refs.ticketForm.elements.category;
    if (select && select.options.length !== categories.length) {
      select.innerHTML = "";
      categories.forEach(function (category) {
        var option = document.createElement("option");
        option.value = category;
        option.textContent = category;
        select.appendChild(option);
      });
    }

    refs.error.hidden = !S.error;
    refs.error.textContent = S.error || "";
    refs.quick.innerHTML = "";
    (S.config.quick_replies || DEFAULT_CONFIG.quick_replies).forEach(function (text) {
      var chip = el("button", "iq-chip", text);
      chip.type = "button";
      refs.quick.appendChild(chip);
    });

    renderMessages();
  }

  function safeUrl(value) {
    var raw = String(value || "");
    if (/^https?:\/\//i.test(raw)) return raw;
    if (raw.charAt(0) === "/" && raw.charAt(1) !== "/") return raw;
    return "";
  }

  function richCard(kindLabel, title, description, url, actionLabel) {
    var card = el("div", "iq-card");
    card.appendChild(el("span", "iq-card-kind", kindLabel));
    card.appendChild(el("p", "iq-card-title", title));
    if (description) card.appendChild(el("p", "iq-card-text", description));
    var href = safeUrl(url);
    if (href) {
      var link = el("a", "iq-card-action", actionLabel || "Abrir");
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.appendChild(link);
    }
    return card;
  }

  function updateFormDraft(messageId, key, value) {
    var draft = S.formDrafts[messageId] || {};
    draft[key] = value;
    S.formDrafts[messageId] = draft;
  }

  function formCard(message) {
    var payload = message.payload || {};
    var fields = Array.isArray(payload.fields) ? payload.fields : [];
    var card = el("div", "iq-card iq-form-card");
    card.appendChild(el("span", "iq-card-kind", "Formulário"));
    card.appendChild(el("p", "iq-card-title", payload.title || "Formulário"));
    if (payload.description) card.appendChild(el("p", "iq-card-text", payload.description));

    var response = message.form_response;
    if (response && response.values) {
      var done = el("div", "iq-form-done");
      done.appendChild(el("p", "iq-form-done-title", "Resposta enviada"));
      fields.forEach(function (field) {
        var value = response.values[field.key];
        if (!value) return;
        var line = el("p", "iq-form-answer");
        line.appendChild(el("span", "iq-form-answer-label", field.label + ": "));
        line.appendChild(document.createTextNode(value));
        done.appendChild(line);
      });
      if (response.submitted_at) {
        done.appendChild(el("p", "iq-form-answer", "Enviado em " + relativeTime(response.submitted_at)));
      }
      card.appendChild(done);
      return card;
    }

    var form = el("form", "iq-form");
    var draft = S.formDrafts[message.id] || {};
    fields.forEach(function (field) {
      var wrapper = el("label", "iq-field");
      wrapper.appendChild(el("span", null, field.label + (field.required ? " *" : "")));
      var input;
      if (field.type === "textarea") {
        input = document.createElement("textarea");
        input.rows = 3;
      } else if (field.type === "select") {
        input = document.createElement("select");
        var empty = document.createElement("option");
        empty.value = "";
        empty.textContent = "Escolha…";
        input.appendChild(empty);
        (field.options || []).forEach(function (option) {
          var node = document.createElement("option");
          node.value = option;
          node.textContent = option;
          input.appendChild(node);
        });
      } else {
        input = document.createElement("input");
        input.type =
          field.type === "email" || field.type === "tel" || field.type === "number" || field.type === "date"
            ? field.type
            : "text";
      }
      input.name = field.key;
      input.required = !!field.required;
      if (field.placeholder) input.placeholder = field.placeholder;
      if (draft[field.key] !== undefined) input.value = draft[field.key];
      input.addEventListener("input", function () {
        updateFormDraft(message.id, field.key, input.value);
      });
      input.addEventListener("change", function () {
        updateFormDraft(message.id, field.key, input.value);
      });
      wrapper.appendChild(input);
      form.appendChild(wrapper);
    });
    var submit = el("button", "iq-primary", payload.submit_label || "Enviar");
    submit.type = "submit";
    submit.disabled = !!S.formBusy[message.id];
    submit.textContent = S.formBusy[message.id] ? "A enviar…" : payload.submit_label || "Enviar";
    form.appendChild(submit);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (S.formBusy[message.id]) return;
      var values = {};
      fields.forEach(function (field) {
        var input = form.elements[field.key];
        values[field.key] = input ? input.value : "";
      });
      S.formBusy[message.id] = true;
      S.error = "";
      render();
      api("/support/sessions/" + encodeURIComponent(S.sessionId) + "/forms/" + encodeURIComponent(message.id), {
        method: "POST",
        body: { values: values },
      })
        .then(function (data) {
          S.formBusy[message.id] = false;
          if (data && data.message) upsertMessage(data.message);
          if (data && data.session) S.session = data.session;
          delete S.formDrafts[message.id];
          render();
          scrollToEnd();
        })
        .catch(function (error) {
          S.formBusy[message.id] = false;
          S.error = error.message || "Não foi possível enviar o formulário.";
          render();
        });
    });
    card.appendChild(form);
    return card;
  }

  function renderMessages() {
    var list = refs.scroll;
    if (!list) return;
    var active = root && root.activeElement;
    var activeName = active && active.getAttribute ? active.getAttribute("name") : "";
    var selectionStart = active && typeof active.selectionStart === "number" ? active.selectionStart : null;
    list.innerHTML = "";
    var lastAuthor = "";
    S.messages.forEach(function (message) {
      var author = message.author_type || "system";
      if (author === "system") {
        var system = el("p", "iq-system", message.body);
        list.appendChild(system);
        lastAuthor = author;
        return;
      }
      var kind = message.kind || "text";
      if (kind === "link" || kind === "report" || kind === "form") {
        var richRow = el("div", "iq-rich is-" + author);
        var payload = message.payload || {};
        if (kind === "link") {
          richRow.appendChild(
            richCard("Link", payload.title || payload.url, payload.description, payload.url, "Abrir link"),
          );
        } else if (kind === "report") {
          richRow.appendChild(
            richCard(
              "Relatório" + (payload.free ? " · gratuito" : ""),
              payload.title || "Relatório",
              payload.summary,
              payload.url,
              "Abrir relatório",
            ),
          );
        } else {
          richRow.appendChild(formCard(message));
        }
        var richMeta = el("span", "iq-meta", (message.author_name || "Equipa") + " · " + relativeTime(message.created_at));
        richRow.appendChild(richMeta);
        list.appendChild(richRow);
        lastAuthor = author;
        return;
      }
      var row = el("div", "iq-row is-" + author);
      if (lastAuthor !== author) {
        var name = el("span", "iq-author", message.author_name || (author === "operator" ? "Equipa" : "Você"));
        row.appendChild(name);
      }
      var bubble = el("div", "iq-bubble" + (message.pending ? " is-pending" : "") + (message.failed ? " is-failed" : ""));
      bubble.textContent = message.body || "";
      row.appendChild(bubble);
      var meta = el("span", "iq-meta", relativeTime(message.created_at));
      row.appendChild(meta);
      list.appendChild(row);
      lastAuthor = author;
    });
    if (activeName) {
      var again = list.querySelector('[name="' + (window.CSS && window.CSS.escape ? window.CSS.escape(activeName) : activeName) + '"]');
      if (again) {
        again.focus();
        try {
          if (selectionStart !== null && typeof again.setSelectionRange === "function") {
            again.setSelectionRange(selectionStart, selectionStart);
          }
        } catch (error) {
          /* tipo de campo sem seleção */
        }
      }
    }
  }

  function scrollToEnd() {
    if (!refs.scroll) return;
    window.setTimeout(function () {
      refs.scroll.scrollTop = refs.scroll.scrollHeight;
    }, 30);
  }

  /* ------------------------------------------------------------------ estilo */
  var CSS = `
:host { all: initial; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
.iq-wrap {
  position: fixed; z-index: 2147483000; right: 20px; bottom: 20px;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color: #e2e8f0; font-size: 14px; line-height: 1.45;
}
.iq-launcher {
  width: 56px; height: 56px; border-radius: 999px; border: 1px solid rgba(255,255,255,.14);
  display: grid; place-items: center; cursor: pointer; color: #052e2b; position: relative;
  background: linear-gradient(135deg, #5eead4, #2dd4bf 45%, #0ea5e9);
  box-shadow: 0 12px 30px rgba(13,148,136,.35), 0 2px 8px rgba(0,0,0,.35);
  transition: transform .16s ease, box-shadow .16s ease;
}
.iq-launcher:hover { transform: translateY(-2px); box-shadow: 0 16px 36px rgba(13,148,136,.45); }
.iq-launcher svg { width: 26px; height: 26px; }
.iq-badge {
  position: absolute; top: -4px; right: -4px; min-width: 20px; height: 20px; padding: 0 5px;
  border-radius: 999px; background: #f43f5e; color: #fff; font-size: 11px; font-weight: 700;
  display: grid; place-items: center; border: 2px solid #0b1220;
}
.iq-panel {
  position: absolute; right: 0; bottom: 72px; width: 380px; max-width: calc(100vw - 24px);
  height: 580px; max-height: calc(100vh - 110px); display: flex; flex-direction: column;
  border-radius: 18px; overflow: hidden; background: #0b1220;
  border: 1px solid rgba(148,163,184,.22);
  box-shadow: 0 24px 70px rgba(2,6,23,.65), 0 4px 18px rgba(0,0,0,.35);
  animation: iq-in .18s ease-out;
}
@keyframes iq-in { from { opacity: 0; transform: translateY(8px) scale(.98); } to { opacity: 1; transform: none; } }
.iq-header {
  display: flex; align-items: center; gap: 10px; padding: 12px 14px;
  background: linear-gradient(135deg, rgba(45,212,191,.16), rgba(14,165,233,.12));
  border-bottom: 1px solid rgba(148,163,184,.16);
}
.iq-avatar {
  width: 36px; height: 36px; border-radius: 999px; display: grid; place-items: center;
  background: linear-gradient(135deg, #2dd4bf, #0ea5e9); color: #042f2e;
}
.iq-avatar svg { width: 18px; height: 18px; }
.iq-heading { min-width: 0; flex: 1; }
.iq-title { margin: 0; font-size: 13.5px; font-weight: 700; letter-spacing: .1px; }
.iq-status { margin: 1px 0 0; display: flex; align-items: center; gap: 6px; font-size: 11px; color: #94a3b8; }
.iq-dot { width: 7px; height: 7px; border-radius: 999px; background: #64748b; }
.iq-dot.is-online { background: #34d399; box-shadow: 0 0 0 3px rgba(52,211,153,.15); }
.iq-dot.is-hours { background: #fbbf24; }
.iq-dot.is-offline { background: #64748b; }
.iq-icon-button {
  width: 30px; height: 30px; display: grid; place-items: center; cursor: pointer;
  border: 0; border-radius: 8px; background: transparent; color: #94a3b8;
}
.iq-icon-button:hover { background: rgba(148,163,184,.14); color: #e2e8f0; }
.iq-icon-button svg { width: 17px; height: 17px; }
.iq-body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.iq-chat { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.iq-chat[hidden], .iq-ticket-view[hidden] { display: none; }
.iq-messages {
  flex: 1; min-height: 0; overflow-y: auto; padding: 14px;
  display: flex; flex-direction: column; gap: 9px; scroll-behavior: smooth;
  background: radial-gradient(1200px 400px at 20% 0%, rgba(45,212,191,.06), transparent 60%);
}
.iq-messages::-webkit-scrollbar { width: 8px; }
.iq-messages::-webkit-scrollbar-thumb { background: rgba(148,163,184,.25); border-radius: 8px; }
.iq-row { display: flex; flex-direction: column; max-width: 84%; gap: 3px; }
.iq-row.is-visitor { align-self: flex-end; align-items: flex-end; }
.iq-row.is-operator { align-self: flex-start; align-items: flex-start; }
.iq-author { font-size: 10.5px; color: #94a3b8; padding: 0 4px; }
.iq-bubble {
  padding: 9px 12px; border-radius: 14px; white-space: pre-wrap; word-break: break-word;
  font-size: 13px; border: 1px solid transparent;
}
.iq-row.is-visitor .iq-bubble { background: linear-gradient(135deg, #2dd4bf, #14b8a6); color: #042f2e; border-bottom-right-radius: 4px; }
.iq-row.is-operator .iq-bubble { background: rgba(148,163,184,.13); color: #e2e8f0; border-color: rgba(148,163,184,.14); border-bottom-left-radius: 4px; }
.iq-bubble.is-pending { opacity: .65; }
.iq-bubble.is-failed { background: rgba(244,63,94,.18); color: #fecdd3; border-color: rgba(244,63,94,.35); }
.iq-meta { font-size: 10px; color: #64748b; padding: 0 4px; }
.iq-rich { display: flex; flex-direction: column; gap: 4px; max-width: 92%; }
.iq-rich.is-operator { align-self: flex-start; align-items: flex-start; }
.iq-rich.is-visitor { align-self: flex-end; align-items: flex-end; }
.iq-card {
  display: flex; flex-direction: column; gap: 6px; width: 100%; padding: 10px 12px;
  border-radius: 12px; border: 1px solid rgba(45,212,191,.28);
  background: linear-gradient(160deg, rgba(45,212,191,.12), rgba(14,165,233,.07));
}
.iq-card-kind {
  align-self: flex-start; border-radius: 999px; padding: 1px 8px; font-size: 9.5px;
  text-transform: uppercase; letter-spacing: .4px; color: #99f6e4;
  background: rgba(45,212,191,.16); border: 1px solid rgba(94,234,212,.24);
}
.iq-card-title { margin: 0; font-size: 13px; font-weight: 700; color: #f1f5f9; }
.iq-card-text { margin: 0; font-size: 11.5px; color: #94a3b8; white-space: pre-wrap; }
.iq-card-action {
  align-self: flex-start; margin-top: 2px; border-radius: 8px; padding: 6px 10px;
  font-size: 11.5px; font-weight: 700; text-decoration: none; color: #042f2e;
  background: linear-gradient(135deg, #5eead4, #22d3ee);
}
.iq-card-action:hover { filter: brightness(1.05); }
.iq-form { display: flex; flex-direction: column; gap: 7px; width: 100%; }
.iq-form .iq-primary { margin-top: 2px; }
.iq-form-done { display: flex; flex-direction: column; gap: 3px; }
.iq-form-done-title { margin: 0 0 2px; font-size: 11.5px; font-weight: 700; color: #5eead4; }
.iq-form-answer { margin: 0; font-size: 11.5px; color: #cbd5e1; white-space: pre-wrap; }
.iq-form-answer-label { color: #94a3b8; font-weight: 600; }
.iq-system {
  align-self: center; max-width: 92%; text-align: center; font-size: 11px;
  color: #94a3b8; background: rgba(148,163,184,.09); border-radius: 999px; padding: 4px 10px; margin: 2px 0;
}
.iq-typing { margin: 0; padding: 0 16px 6px; font-size: 11px; color: #5eead4; }
.iq-start { padding: 14px; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
.iq-greeting { margin: 0; font-size: 15px; font-weight: 600; }
.iq-away { margin: 0; font-size: 12px; color: #94a3b8; }
.iq-start-form, .iq-ticket-form { display: flex; flex-direction: column; gap: 8px; }
.iq-field { display: flex; flex-direction: column; gap: 4px; font-size: 11.5px; color: #94a3b8; }
.iq-field input, .iq-field select, .iq-field textarea, .iq-input {
  width: 100%; border-radius: 10px; border: 1px solid rgba(148,163,184,.24);
  background: rgba(15,23,42,.85); color: #e2e8f0; padding: 9px 10px; font: inherit; outline: none;
}
.iq-field input:focus, .iq-field select:focus, .iq-field textarea:focus, .iq-input:focus {
  border-color: rgba(45,212,191,.65); box-shadow: 0 0 0 3px rgba(45,212,191,.12);
}
.iq-primary {
  width: 100%; border: 0; border-radius: 10px; padding: 10px 12px; cursor: pointer;
  font-weight: 700; font-size: 13px; color: #042f2e;
  background: linear-gradient(135deg, #5eead4, #2dd4bf 55%, #22d3ee);
}
.iq-primary:disabled { opacity: .6; cursor: default; }
.iq-quick { display: flex; flex-wrap: wrap; gap: 6px; }
.iq-chip {
  border: 1px solid rgba(94,234,212,.28); background: rgba(45,212,191,.08); color: #99f6e4;
  border-radius: 999px; padding: 5px 10px; font-size: 11.5px; cursor: pointer;
}
.iq-chip:hover { background: rgba(45,212,191,.16); }
.iq-link { border: 0; background: none; color: #7dd3fc; font-size: 11.5px; cursor: pointer; padding: 2px; text-align: left; }
.iq-link:hover { text-decoration: underline; }
.iq-composer {
  display: flex; gap: 8px; align-items: flex-end; padding: 10px;
  border-top: 1px solid rgba(148,163,184,.14); background: rgba(2,6,23,.35);
}
.iq-input { resize: none; max-height: 120px; min-height: 40px; line-height: 1.35; }
.iq-send {
  width: 40px; height: 40px; flex: 0 0 40px; border-radius: 10px; border: 0; cursor: pointer;
  display: grid; place-items: center; color: #042f2e;
  background: linear-gradient(135deg, #5eead4, #22d3ee);
}
.iq-send svg { width: 18px; height: 18px; }
.iq-send:disabled { opacity: .5; }
.iq-footer { display: flex; justify-content: space-between; gap: 8px; padding: 0 14px 10px; }
.iq-closed { padding: 14px; display: flex; flex-direction: column; gap: 10px; align-items: center; text-align: center; }
.iq-closed[hidden] { display: none; }
.iq-closed p { margin: 0; color: #94a3b8; font-size: 12.5px; }
.iq-stars { display: flex; gap: 4px; }
.iq-star { background: none; border: 0; color: #fbbf24; font-size: 22px; cursor: pointer; line-height: 1; }
.iq-star:hover { transform: scale(1.08); }
.iq-ticket-view { flex: 1; overflow-y: auto; padding: 12px 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.iq-ticket-head { display: flex; align-items: center; gap: 8px; }
.iq-ticket-title { margin: 0; font-size: 13.5px; font-weight: 700; }
.iq-error {
  margin: 0; padding: 8px 14px; font-size: 11.5px; color: #fecdd3;
  background: rgba(244,63,94,.12); border-top: 1px solid rgba(244,63,94,.24);
}
.iq-error[hidden] { display: none; }
@media (max-width: 480px) {
  .iq-wrap { right: 12px; bottom: 12px; left: 12px; }
  .iq-launcher { margin-left: auto; }
  .iq-panel { bottom: 68px; width: 100%; height: calc(100vh - 110px); max-height: none; }
}
`;

  /* ------------------------------------------------------------------- init */
  function init() {
    load();
    build();
    installPageTracking();
    pollTimer = window.setInterval(function () {
      if (S.open && S.sessionId && !S.connected) refreshSession();
    }, 10000);
    boot();
  }

  function boot() {
    bootstrap()
      .then(function () {
        if (!S.config.available && !S.config.operators_online) {
          S.config.available = false;
        }
        connect();
        if (S.sessionId) {
          refreshSession();
        }
      })
      .catch(function (error) {
        S.error = error.message || "Apoio indisponível.";
        render();
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  window.IQOSSupport = {
    open: function () {
      setOpen(true);
    },
    close: function () {
      setOpen(false);
    },
    reset: resetConversation,
    config: function () {
      return S.config;
    },
  };
})();
