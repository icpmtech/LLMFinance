const { chromium } = require("C:\\Users\\pedro.mourao.martins\\.vscode\\extensions\\danielsanmedium.dscodegpt-3.24.75\\standalone\\node_modules\\patchright");
const fs = require("fs");
const TOKEN = fs.readFileSync("C:/LLMFinance/finance-llm/logs/_tmp_token.txt", "utf8").trim();
const OUT = "C:/LLMFinance/finance-llm/logs/_qa_result2.json";
const R = { steps: [], console: [], failed: [] };

(async () => {
  const b = await chromium.launch({ headless: true });
  const p = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
  p.on("console", (m) => {
    if (m.type() === "error") R.console.push(m.text().slice(0, 200));
  });
  p.on("requestfailed", (r) => R.failed.push(r.url()));

  try {
    await p.goto("http://127.0.0.1:8002/", { waitUntil: "domcontentloaded" });
    await p.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), TOKEN);
    await p.goto("http://127.0.0.1:8002/empresas-iq", { waitUntil: "domcontentloaded" });
    await p.waitForTimeout(5000);

    await p.locator('[role="tab"]', { hasText: "Contratos Públicos" }).first().click();
    await p.waitForTimeout(6000);

    // Abrir a ficha do contrato pelo botão do nº
    await p.locator("tbody tr td:first-child button", { hasText: "15609253" }).first().click();
    await p.waitForTimeout(8000);
    R.steps.push({
      label: "ficha aberta",
      hasPanel: await p.evaluate(() => /An\u00e1lise IA/i.test(document.body.innerText)),
      hasField: await p.evaluate(() => !!document.querySelector('textarea[placeholder*="riscos de corrup"]')),
    });

    const btn = p.locator("button", { hasText: "Analisar contrato" }).first();
    await btn.waitFor({ state: "visible", timeout: 60000 });
    await btn.scrollIntoViewIfNeeded();

    const ta = p.locator('textarea[placeholder*="riscos de corrup"]').first();
    await ta.fill("Identifica riscos, partes, valor e procedimento deste contrato.");

    // modelo vazio = provider do sistema
    const model = p.locator('input[placeholder*="llama3.2"]').first();
    if (await model.count()) R.modelValue = await model.inputValue();

    const before = await p.evaluate(() => document.body.innerText.length);
    await btn.click();
    R.steps.push({ label: "analise lancada" });

    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) {
      await p.waitForTimeout(4000);
      const st = await p.evaluate(() => {
        const b2 = Array.from(document.querySelectorAll("button")).find((x) =>
          /Analisar contrato/i.test(x.textContent || ""),
        );
        const t = document.body.innerText;
        return { busy: b2 ? b2.disabled : false, len: t.length, tail: t.slice(-3000) };
      });
      const err = /Erro ao analisar contrato[^\n]*/.exec(st.tail);
      if (err) {
        R.error = err[0];
        R.tail = st.tail;
        break;
      }
      if (!st.busy && st.len > before + 300) {
        const i = st.tail.indexOf("Análise IA");
        R.answer = (i >= 0 ? st.tail.slice(i) : st.tail).slice(0, 2200);
        break;
      }
    }
  } catch (e) {
    R.exception = String(e).slice(0, 400);
  } finally {
    fs.writeFileSync(OUT, JSON.stringify(R, null, 2), "utf8");
    await b.close();
  }
})();
