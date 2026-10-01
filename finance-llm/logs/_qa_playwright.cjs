// QA Playwright: fluxo real da Análise IA de contrato em 8002
const { chromium } = require("C:\\Users\\pedro.mourao.martins\\.vscode\\extensions\\danielsanmedium.dscodegpt-3.24.75\\standalone\\node_modules\\patchright");
const fs = require("fs");

const TOKEN = fs.readFileSync("C:/LLMFinance/finance-llm/logs/_tmp_token.txt", "utf8").trim();
const OUT = "C:/LLMFinance/finance-llm/logs/_qa_result.json";
const BASE = "http://127.0.0.1:8002";

const result = { steps: [], console: [], failed: [] };

async function diag(page, label) {
  const d = await page.evaluate(() => ({
    url: location.href,
    tabs: Array.from(document.querySelectorAll('[role="tab"]')).map((t) => (t.textContent || "").trim()),
    inputs: Array.from(document.querySelectorAll("input,textarea")).map((i) => ({
      tag: i.tagName,
      type: i.type || "",
      ph: i.placeholder || "",
    })),
    buttons: Array.from(document.querySelectorAll("button"))
      .map((b) => (b.textContent || "").trim())
      .filter((t) => /analis|contrato|pesquis|grafo|entidade/i.test(t))
      .slice(0, 20),
    text: document.body.innerText.slice(0, 400),
  }));
  result.steps.push({ label, ...d });
  return d;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();

  page.on("console", (m) => {
    if (m.type() === "error") result.console.push(m.text().slice(0, 200));
  });
  page.on("requestfailed", (r) => result.failed.push(r.url()));

  try {
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
    await page.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), TOKEN);

    await page.goto(BASE + "/empresas-iq", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(6000);
    await diag(page, "empresas-iq inicial");

    // 1) separador Contratos Públicos
    const tab = page.locator('[role="tab"]', { hasText: "Contratos Públicos" }).first();
    await tab.click({ timeout: 20000 });
    await page.waitForTimeout(4000);
    await diag(page, "apos tab contratos");

    // 2) pesquisa
    const search = page
      .locator('input[type="search"], input[placeholder*="esquisar" i], input[placeholder*="contrato" i]')
      .first();
    await search.waitFor({ state: "visible", timeout: 20000 });
    await search.fill("15609253");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(8000);
    await diag(page, "apos pesquisa");

    // 3) abrir resultado
    let opened = false;
    const hit = page.locator("button,[role=button],a,li,tr").filter({ hasText: /15609253/ }).first();
    if (await hit.count()) {
      await hit.click();
      opened = true;
    }
    result.steps.push({ label: "clique resultado", opened });
    await page.waitForTimeout(8000);
    await diag(page, "apos abrir contrato");

    // 4) painel de Análise IA
    const btn = page.locator("button", { hasText: "Analisar contrato" }).first();
    await btn.waitFor({ state: "visible", timeout: 60000 });
    await btn.scrollIntoViewIfNeeded();
    result.steps.push({ label: "painel encontrado" });

    const ta = page.locator('textarea[placeholder*="riscos de corrup"]').first();
    await ta.fill("Identifica riscos, partes, valor e procedimento.");
    const beforeLen = await page.evaluate(() => document.body.innerText.length);
    await btn.click();
    result.steps.push({ label: "analise lancada" });

    const deadline = Date.now() + 180000;
    let done = false;
    while (Date.now() < deadline) {
      await page.waitForTimeout(4000);
      const st = await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll("button")).find((x) =>
          /Analisar contrato/i.test(x.textContent || ""),
        );
        const t = document.body.innerText;
        return { busy: b ? b.disabled : false, len: t.length, tail: t.slice(-2500) };
      });
      const err = /Erro ao analisar contrato[^\n]*/.exec(st.tail);
      if (err) {
        result.error = err[0];
        result.tail = st.tail;
        done = true;
        break;
      }
      if (!st.busy && st.len > beforeLen + 300) {
        const i = st.tail.indexOf("Análise IA");
        result.answer = (i >= 0 ? st.tail.slice(i) : st.tail).slice(0, 2000);
        done = true;
        break;
      }
    }
    result.done = done;
    if (!done) result.tail = await page.evaluate(() => document.body.innerText.slice(-1500));
  } catch (e) {
    result.exception = String(e).slice(0, 400);
    try {
      await diag(page, "erro");
    } catch {}
  } finally {
    fs.writeFileSync(OUT, JSON.stringify(result, null, 2), "utf8");
    await browser.close();
  }
})();
