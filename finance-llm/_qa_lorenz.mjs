// QA temporário da página /lorenz: título, KPIs, gráficos, alertas e propagação.
export async function run(page) {
  const token = process.env.IQOS_TEST_TOKEN || "";
  await page.addInitScript((t) => {
    try {
      window.localStorage.setItem("finance-llm-token", t);
    } catch {}
  }, token);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(page.url(), { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(12000);

  const texto = (valor) => (valor || "").replace(/\s+/g, " ").trim();

  const ler = () =>
    page.evaluate(() => {
      const limpo = (valor) => (valor || "").replace(/\s+/g, " ").trim();
      const main = document.querySelector("main") || document.body;
      const h1 = limpo(main.querySelector("h1")?.textContent);
      const botoes = [...main.querySelectorAll("nav button")].map((b) => limpo(b.textContent));
      const kpis = [...main.querySelectorAll("p.stat-value")].map((p) => limpo(p.textContent)).slice(0, 6);
      return {
        h1,
        secoes: botoes,
        kpis,
        chips: [...main.querySelectorAll("span")].map((s) => limpo(s.textContent)).filter((t) => /Amplificador|Dissipador|Sensível/.test(t)).slice(0, 3),
        graficos: main.querySelectorAll(".recharts-surface").length,
        canvas: main.querySelectorAll("canvas").length,
        alertas: [...main.querySelectorAll("li")].map((li) => limpo(li.textContent)).filter((t) => /extrema|CPU|cpu|amplifica|um só fornecedor|fornecedor/i.test(t)).length,
        tabelas: main.querySelectorAll("table").length,
        erros: [...main.querySelectorAll("div")].map((d) => limpo(d.textContent)).filter((t) => /^Erro|HTTP 5|HTTP 4/.test(t)).slice(0, 3),
      };
    });

  const inicial = await ler();

  // Muda para a secção «Propagação», escolhe 60 dias e simula
  const clicou = await page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    const nav = main.querySelector("nav");
    const alvo = [...(nav?.querySelectorAll("button") || [])].find((b) => /Propagação/.test(b.textContent || ""));
    if (!alvo) return false;
    alvo.click();
    return true;
  });
  await page.waitForTimeout(1500);
  await page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    const sessenta = [...main.querySelectorAll("button")].find((b) => (b.textContent || "").trim() === "60 dias");
    sessenta?.click();
  });
  await page.waitForTimeout(400);
  await page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    const simular = [...main.querySelectorAll("button")].find((b) => /Simular propagação/.test(b.textContent || ""));
    simular?.click();
  });
  await page.waitForTimeout(14000);
  const depois = await ler();

  const propagacao = await page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    const linhas = [...main.querySelectorAll("table tbody tr")].map((tr) => (tr.textContent || "").replace(/\s+/g, " ").trim().slice(0, 120));
    return { tabelas: main.querySelectorAll("table").length, linhas: linhas.slice(0, 8), resumo: (main.textContent || "").replace(/\s+/g, " ").slice(0, 400) };
  });

  // Secção CPV
  await page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    const alvo = [...(main.querySelector("nav")?.querySelectorAll("button") || [])].find((b) => (b.textContent || "").trim() === "CPV");
    alvo?.click();
  });
  await page.waitForTimeout(1200);
  const cpv = await page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    const cabecalho = [...(main.querySelectorAll("table th") || [])].map((th) => (th.textContent || "").trim());
    const primeira = [...(main.querySelectorAll("table tbody tr") || [])][0]?.textContent?.replace(/\s+/g, " ").trim().slice(0, 140);
    return { cabecalho: cabecalho.slice(0, 10), primeira };
  });

  // Secção Grafo (construir a pedido)
  await page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    const alvo = [...(main.querySelector("nav")?.querySelectorAll("button") || [])].find((b) => (b.textContent || "").trim() === "Grafo");
    alvo?.click();
  });
  await page.waitForTimeout(800);
  await page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    const construir = [...main.querySelectorAll("button")].find((b) => /Construir grafo/.test(b.textContent || ""));
    construir?.click();
  });
  await page.waitForTimeout(16000);
  const grafo = await page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    return { canvas: main.querySelectorAll("canvas").length, texto: (main.textContent || "").replace(/\s+/g, " ").slice(-260) };
  });

  return { bundle: await page.evaluate(() => [...document.querySelectorAll("script[src]")].map((s) => s.src)), inicial, clicou, depois, propagacao, cpv, grafo, texto: texto(inicial.h1) };
}
