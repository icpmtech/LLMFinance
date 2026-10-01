import fs from "node:fs";

const log = [];

export default async function run(page, ui) {
  const token = fs.readFileSync("C:/LLMFinance/finance-llm/logs/_tmp_token.txt", "utf8").trim();

  await page.goto("http://127.0.0.1:8002/", { waitUntil: "domcontentloaded" });
  await page.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), token);
  await page.goto("http://127.0.0.1:8002/empresas-iq", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(5000);

  await page.getByRole("tab", { name: /Contratos P\u00fablicos/i }).first().click();
  await page.waitForTimeout(4000);
  log.push("tab contratos ok");

  const search = page.locator('input[type="search"], input[placeholder*="esquisar" i], input[placeholder*="Pesquisar" i]').first();
  await search.waitFor({ state: "visible", timeout: 30000 });
  await search.fill("15609253");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(7000);
  log.push("pesquisa submetida: " + (await search.inputValue()));

  const hit = page.locator("button, [role=button], a, li").filter({ hasText: /15609253/ }).first();
  if (await hit.count()) {
    await hit.click();
  } else {
    return {
      stage: "sem resultado",
      log,
      text: await page.evaluate(() => document.body.innerText.slice(0, 1500)),
    };
  }
  await page.waitForTimeout(8000);
  log.push("resultado clicado");

  const btn = page.locator("button", { hasText: /Analisar contrato/i }).first();
  try {
    await btn.scrollIntoViewIfNeeded();
    await btn.waitFor({ state: "visible", timeout: 60000 });
  } catch {
    return {
      stage: "painel nao encontrado",
      log,
      text: await page.evaluate(() => document.body.innerText.slice(-1500)),
    };
  }
  log.push("painel encontrado");

  const ta = page.locator('textarea[placeholder*="riscos de corrup"]').first();
  await ta.fill("Identifica riscos, partes, valor e procedimento.");
  const before = await page.evaluate(() => document.body.innerText.length);
  await btn.click();
  log.push("analise lancada");

  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    await page.waitForTimeout(4000);
    const st = await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll("button")).find((x) =>
        /Analisar contrato/i.test(x.textContent || ""),
      );
      const t = document.body.innerText;
      return {
        busy: b ? b.disabled : false,
        len: t.length,
        err: (/Erro ao analisar contrato[^\n]*/.exec(t) || [""])[0],
      };
    });
    if (st.err) return { stage: "erro UI", err: st.err, log };
    if (!st.busy && st.len > before + 300) {
      const ans = await page.evaluate(() => {
        const t = document.body.innerText;
        const i = t.indexOf("An\u00e1lise IA");
        return t.slice(i >= 0 ? i : Math.max(0, t.length - 2500));
      });
      return { stage: "ok", ok: true, log, answer: ans.slice(0, 1800) };
    }
  }
  return { stage: "timeout", log, text: await page.evaluate(() => document.body.innerText.slice(-1200)) };
}
