import fs from "node:fs";

export default async function run(page, ui) {
  const token = fs.readFileSync("C:/LLMFinance/finance-llm/logs/_tmp_token.txt", "utf8").trim();

  await page.goto("http://127.0.0.1:8002/", { waitUntil: "domcontentloaded" });
  await page.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), token);

  await page.goto("http://127.0.0.1:8002/empresas-iq", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);

  return {
    url: page.url(),
    title: await page.title(),
    scripts: await page.evaluate(() =>
      Array.from(document.querySelectorAll("script[src]")).map((s) => s.getAttribute("src")),
    ),
    text: await page.evaluate(() => document.body.innerText.slice(0, 1200)),
    snapshot: await ui.snapshot(),
  };
}
