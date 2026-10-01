import fs from "node:fs";

export default async function run(page, ui) {
  const token = fs.readFileSync("C:/LLMFinance/finance-llm/logs/_tmp_token.txt", "utf8").trim();

  await page.goto("http://127.0.0.1:8002/", { waitUntil: "domcontentloaded" });
  await page.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), token);

  await page.goto("http://127.0.0.1:8002/empresas-iq/15609253", { waitUntil: "domcontentloaded" });

  // Esperar pelo painel de Análise IA
  const btn = page.locator("main button", { hasText: /Analisar contrato/i }).first();
  await btn.waitFor({ state: "visible", timeout: 90000 });

  const ta = page.locator('main textarea[placeholder*="riscos de corrup"]').first();
  await ta.fill("Identifica riscos, partes, valor e procedimento deste contrato.");

  const before = await page.evaluate(() => document.querySelector("main").innerText.length);
  await btn.click();

  // Esperar que a análise termine (botão volta a ficar ativo) e detetar resposta
  let answerText = "";
  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    await page.waitForTimeout(3000);
    const state = await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll("main button")).find((x) =>
        /Analisar contrato/i.test(x.textContent || ""),
      );
      const main = document.querySelector("main");
      const err = main ? /Erro ao analisar contrato[^\n]*/i.exec(main.innerText)?.[0] || "" : "";
      return {
        spinning: b ? b.disabled : false,
        len: main ? main.innerText.length : 0,
        err,
        hasBackend: /deepseek|ollama|openai|local:/i.test(main ? main.innerText : ""),
      };
    });
    if (state.err) return { stage: "erro", err: state.err };
    if (!state.spinning && state.len > before + 200) {
      answerText = await page.evaluate(() => {
        const main = document.querySelector("main");
        const t = main.innerText;
        const i = t.search(/An\u00e1lise|Resposta|deepseek|##/i);
        return t.slice(Math.max(0, i), i + 2500);
      });
      break;
    }
  }

  return {
    ok: answerText.length > 0,
    grew: before,
    answer: answerText || "(sem resposta detetada)",
  };
}
