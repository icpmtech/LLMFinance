import fs from "node:fs";

const log = [];

export default async function run(page, ui) {
  const token = fs.readFileSync("C:/LLMFinance/finance-llm/logs/_tmp_token.txt", "utf8").trim();

  await page.goto("http://127.0.0.1:8002/", { waitUntil: "domcontentloaded" });
  await page.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), token);
  await page.goto("http://127.0.0.1:8002/empresas-iq", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000);

  // 1) Abrir o separador de Contratos Públicos
  const tabContratos = page.locator("main").getByRole("tab", { name: /Contratos P\u00fablicos/i }).first();
  await tabContratos.click();
  await page.waitForTimeout(3000);
  log.push("tab contratos ok");

  // 2) Pesquisar pelo id do contrato
  const search = page.locator('main input[type="search"], main input[placeholder*="esquisar"]').first();
  await search.waitFor({ state: "visible", timeout: 30000 });
  await search.fill("15609253");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(6000);
  log.push("pesquisa submetida");

  // 3) Abrir o primeiro resultado que contenha o id
  const hit = page.locator("main button, main [role=button], main a").filter({ hasText: /15609253/ }).first();
  if (await hit.count()) {
    await hit.click();
  } else {
    const first = page.locator("main li button, main [data-result] button").first();
    if (await first.count()) await first.click();
    else
      return {
        stage: "sem resultado clicavel",
        log,
        text: await page.evaluate(() => document.querySelector("main").innerText.slice(0, 700)),
      };
  }
  await page.waitForTimeout(6000);
  log.push("resultado clicado");

  // 4) Esperar o painel de Análise IA
  const btn = page.locator("main button", { hasText: /Analisar contrato/i }).first();
  try {
    await btn.waitFor({ state: "visible", timeout: 60000 });
  } catch {
    return {
      stage: "painel nao encontrado",
      log,
      text: await page.evaluate(() => document.querySelector("main").innerText.slice(-1200)),
    };
  }

  const ta = page.locator('main textarea[placeholder*="riscos de corrup"]').first();
  await ta.fill("Identifica riscos, partes, valor e procedimento.");
  const before = await page.evaluate(() => document.querySelector("main").innerText.length);
  await btn.click();
  log.push("analise lancada");

  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    await page.waitForTimeout(4000);
    const st = await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll("main button")).find((x) =>
        /Analisar contrato/i.test(x.textContent || ""),
      );
      const main = document.querySelector("main");
      return {
        busy: b ? b.disabled : false,
        len: main ? main.innerText.length : 0,
        err: (/Erro ao analisar contrato[^\n]*/.exec(main ? main.innerText : "") || [""])[0],
      };
    });
    if (st.err) return { stage: "erro UI", err: st.err, log };
    if (!st.busy && st.len > before + 300) {
      const ans = await page.evaluate(() => {
        const t = document.querySelector("main").innerText;
        const i = t.indexOf("An\u00e1lise IA");
        return t.slice(i >= 0 ? i : Math.max(0, t.length - 2500));
      });
      return { stage: "ok", ok: true, log, answer: ans.slice(0, 1800) };
    }
  }
  return { stage: "timeout", log, text: await page.evaluate(() => document.querySelector("main").innerText.slice(-1000)) };
}
