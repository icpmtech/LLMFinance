import fs from "node:fs";

export default async function run(page, ui) {
  const token = fs.readFileSync("C:/LLMFinance/finance-llm/logs/_tmp_token.txt", "utf8").trim();

  await page.goto("http://127.0.0.1:8002/", { waitUntil: "domcontentloaded" });
  await page.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), token);
  await page.goto("http://127.0.0.1:8002/empresas-iq/15609253", { waitUntil: "domcontentloaded" });

  await page.waitForTimeout(30000);

  const info = await page.evaluate(() => {
    const main = document.querySelector("main");
    const text = main ? main.innerText : document.body.innerText;
    const buttons = Array.from(document.querySelectorAll("main button, main [role=button]"))
      .map((b) => (b.textContent || "").trim())
      .filter(Boolean);
    return {
      textHead: text.slice(0, 900),
      hasAnalise: /an\u00e1lise ia/i.test(text),
      hasModelo: /modelo/i.test(text),
      buttons,
      textareas: Array.from(document.querySelectorAll("main textarea")).map((t) => t.placeholder),
      tabs: Array.from(document.querySelectorAll('main [role="tab"], main button'))
        .map((b) => (b.textContent || "").trim())
        .filter((t) => /an\u00e1lise|ia|contrato/i.test(t))
        .slice(0, 25),
    };
  });

  return info;
}
