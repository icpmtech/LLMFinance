const { chromium } = require("C:\\Users\\pedro.mourao.martins\\.vscode\\extensions\\danielsanmedium.dscodegpt-3.24.75\\standalone\\node_modules\\patchright");
const fs = require("fs");
const TOKEN = fs.readFileSync("C:/LLMFinance/finance-llm/logs/_tmp_token.txt", "utf8").trim();

(async () => {
  const b = await chromium.launch({ headless: true });
  const p = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
  await p.goto("http://127.0.0.1:8002/", { waitUntil: "domcontentloaded" });
  await p.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), TOKEN);
  await p.goto("http://127.0.0.1:8002/empresas-iq", { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(5000);
  await p.locator('[role="tab"]', { hasText: "Contratos Públicos" }).first().click();
  await p.waitForTimeout(6000);

  const info = await p.evaluate(() => {
    const rows = Array.from(document.querySelectorAll("tbody tr"));
    const r = rows[0];
    const cells = r
      ? Array.from(r.querySelectorAll("td")).map((c) => ({
          text: (c.textContent || "").slice(0, 60),
          tag: c.tagName,
          cls: c.className.slice(0, 60),
          inner: c.innerHTML.slice(0, 220),
        }))
      : [];
    return {
      rowCount: rows.length,
      rowCls: r ? r.className : null,
      rowOnClick: r ? !!r.onclick : null,
      cells,
      containerInteractive: Array.from(document.querySelectorAll("main button")).map((x) => ({
        t: (x.textContent || "").trim().slice(0, 40),
        aria: x.getAttribute("aria-label"),
        title: x.getAttribute("title"),
      })),
    };
  });

  fs.writeFileSync("C:/LLMFinance/finance-llm/logs/_qa_row.json", JSON.stringify(info, null, 2), "utf8");
  await b.close();
})();
