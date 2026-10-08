/* ==========================================================================
   sabemos.studio — landing: animações e formulário de registo.
   ========================================================================== */
(() => {
  "use strict";

  const reduzirMovimento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------ reveal ao fazer scroll */
  const revelar = new IntersectionObserver(
    (entradas) => {
      for (const e of entradas) {
        if (e.isIntersecting) {
          e.target.classList.add("visivel");
          revelar.unobserve(e.target);
        }
      }
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
  );
  document.querySelectorAll(".reveal").forEach((el, i) => {
    el.style.transitionDelay = `${Math.min(i % 6, 5) * 70}ms`;
    revelar.observe(el);
  });

  /* --------------------------------------------------- barra fixa solida */
  const topbar = document.getElementById("topbar");
  const aoScroll = () => topbar.classList.toggle("solido", window.scrollY > 24);
  aoScroll();
  window.addEventListener("scroll", aoScroll, { passive: true });

  /* -------------------------------------------------------- contadores */
  const animarContador = (el) => {
    const alvo = Number(el.dataset.count || "0");
    const sufixo = el.dataset.suffix || "";
    if (reduzirMovimento) {
      el.textContent = alvo + sufixo;
      return;
    }
    const duracao = 1200;
    const inicio = performance.now();
    const passo = (agora) => {
      const t = Math.min(1, (agora - inicio) / duracao);
      // easeOutCubic
      const v = Math.round(alvo * (1 - Math.pow(1 - t, 3)));
      el.textContent = v + sufixo;
      if (t < 1) requestAnimationFrame(passo);
    };
    requestAnimationFrame(passo);
  };

  const contadores = new IntersectionObserver(
    (entradas) => {
      for (const e of entradas) {
        if (e.isIntersecting) {
          animarContador(e.target);
          contadores.unobserve(e.target);
        }
      }
    },
    { threshold: 0.4 },
  );
  document.querySelectorAll("[data-count]").forEach((el) => contadores.observe(el));

  /* ------------------------------------------------ leve inclinacao 3D */
  if (!reduzirMovimento) {
    document.querySelectorAll("[data-tilt]").forEach((el) => {
      el.addEventListener("pointermove", (ev) => {
        const r = el.getBoundingClientRect();
        const px = (ev.clientX - r.left) / r.width - 0.5;
        const py = (ev.clientY - r.top) / r.height - 0.5;
        el.style.transform = `perspective(900px) rotateY(${px * 6}deg) rotateX(${-py * 6}deg) translateY(-4px)`;
      });
      el.addEventListener("pointerleave", () => {
        el.style.transform = "";
      });
    });
  }

  /* --------------------------------------------- origem online/offline */
  const bannerOffline = document.getElementById("banner-offline");
  const mostrarBanner = () => {
    if (bannerOffline) bannerOffline.hidden = false;
  };
  fetch("/api/health", { cache: "no-store" })
    .then((r) => (r.ok ? null : mostrarBanner()))
    .catch(() => mostrarBanner());

  /* --------------------------------------------------- contagem publica */
  const contador = document.getElementById("contador");
  const contadorValor = document.getElementById("contador-valor");
  fetch("/api/public/estatisticas", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((dados) => {
      if (!dados || !contador || !contadorValor) return;
      if (Number(dados.total) > 0) {
        contadorValor.textContent = String(dados.total);
        contador.hidden = false;
      }
    })
    .catch(() => {});

  /* ------------------------------------------------------------ formulário */
  const form = document.getElementById("form-registo");
  if (!form) return;

  const botao = form.querySelector(".btn-enviar");
  const rotuloBotao = form.querySelector(".btn-label");
  const sucesso = document.getElementById("sucesso");
  const sucessoTitulo = document.getElementById("sucesso-titulo");
  const sucessoTexto = document.getElementById("sucesso-texto");

  const mostrarErro = (campo, mensagem) => {
    const p = form.querySelector(`[data-erro="${campo}"]`);
    if (!p) return;
    p.textContent = mensagem || "";
    p.hidden = !mensagem;
    const input = form.querySelector(`[name="${campo}"]`);
    if (input) input.classList.toggle("invalido", Boolean(mensagem));
  };

  const limparErros = () => {
    form.querySelectorAll(".erro").forEach((p) => {
      p.hidden = true;
      p.textContent = "";
    });
    form.querySelectorAll(".invalido").forEach((i) => i.classList.remove("invalido"));
  };

  const EMAIL = /^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$/;

  const validar = () => {
    limparErros();
    const nome = form.nome.value.trim();
    const email = form.email.value.trim().toLowerCase();
    let ok = true;

    if (nome.length < 2) {
      mostrarErro("nome", "Indique o seu nome.");
      ok = false;
    }
    if (!EMAIL.test(email)) {
      mostrarErro("email", "Indique um email válido.");
      ok = false;
    }
    if (!form.consentimento.checked) {
      mostrarErro("consentimento", "Precisa de aceitar o contacto para enviar.");
      ok = false;
    }
    return ok;
  };

  form.addEventListener("input", (ev) => {
    const campo = ev.target.name;
    if (campo) mostrarErro(campo, "");
  });

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!validar()) {
      form.querySelector(".invalido, .erro:not([hidden])")?.focus?.();
      return;
    }

    const interesses = Array.from(form.querySelectorAll('input[name="interesse"]:checked')).map((i) => i.value);
    const payload = {
      nome: form.nome.value.trim(),
      email: form.email.value.trim().toLowerCase(),
      organizacao: form.organizacao.value.trim(),
      cargo: form.cargo.value.trim(),
      mensagem: form.mensagem.value.trim(),
      interesse: interesses,
      consentimento: true,
    };

    botao.disabled = true;
    botao.classList.add("a-carregar");
    rotuloBotao.textContent = "A enviar…";

    try {
      const resposta = await fetch("/api/public/registo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const dados = await resposta.json().catch(() => ({}));

      if (!resposta.ok) {
        mostrarErro("geral", dados.erro || "Não foi possível enviar. Tente novamente.");
        return;
      }

      sucessoTitulo.textContent = dados.novo ? "Pedido registado." : "Pedido atualizado.";
      sucessoTexto.textContent = dados.novo
        ? "Obrigado. Entramos em contacto para o email indicado."
        : "Já tínhamos o seu contacto — atualizámos os dados.";
      sucesso.hidden = false;

      if (contador && contadorValor && Number(dados.total) > 0) {
        contadorValor.textContent = String(dados.total);
        contador.hidden = false;
      }

      form.querySelectorAll("input, textarea").forEach((i) => {
        if (i.type === "checkbox") i.checked = false;
        else i.value = "";
      });
      sucesso.scrollIntoView({ behavior: reduzirMovimento ? "auto" : "smooth", block: "center" });
    } catch {
      mostrarErro("geral", "Sem ligação ao servidor. Tente novamente.");
    } finally {
      botao.disabled = false;
      botao.classList.remove("a-carregar");
      rotuloBotao.textContent = "Enviar pedido";
    }
  });
})();
