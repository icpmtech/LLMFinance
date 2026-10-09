/** Diagnóstico: que elementos estouram a largura da página a 390 px. */
const TOKEN =
  "eyJzaWQiOiJhNjljZTlhYTdjMTczMmJmMmI0NjBkY2VkZDc0ZWMxNWMyNzU3NmJiM2YwY2YxZTQiLCJzdWIiOiIzYjFmZjQxNzdiOWFmNDhjNDAwYzM1YjFiMmY2NDYxOSIsImlhdCI6MTc5MTU1OTcxNCwiZXhwIjoxNzkxNjAyOTE0fQ.S6ipiSwmTqzi-abtiHfyfpt1uwN4_gqYfNzPtA70npc";

export default async function run(page) {
  await page.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), TOKEN);
  await page.goto("http://127.0.0.1:4180/subvencoes?v=diag4", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);
  await page.waitForFunction(() => document.body.innerText.includes("Subvenções públicas"), { timeout: 20000 });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(3000);

  const diagnostico = await page.evaluate(() => {
    const todos = Array.from(document.querySelectorAll("main"));
    const raiz = todos[todos.length - 1];
    if (!raiz) return { erro: "sem main" };
    const limite = raiz.getBoundingClientRect();
    const estouram = [];
    raiz.querySelectorAll("*").forEach((el) => {
      const c = el.getBoundingClientRect();
      if (c.width === 0 && c.height === 0) return;
      const excede = Math.round(Math.max(c.right - limite.right, limite.left - c.left));
      const rola = el.scrollWidth - el.clientWidth;
      if (excede > 2 || rola > 2) {
        estouram.push({
          tag: el.tagName,
          cls: (el.className || "").toString().slice(0, 150),
          texto: (el.textContent || "").trim().slice(0, 45),
          largura: Math.round(c.width),
          excede: Math.round(excede),
          rolagemX: Math.round(rola),
          scrollW: el.scrollWidth,
          clientW: el.clientWidth,
        });
      }
    });
    return {
      raizLargura: Math.round(limite.width),
      raizScrollWidth: raiz.scrollWidth,
      raizClientWidth: raiz.clientWidth,
      total: estouram.length,
      // Só os maiores, para a lista ser legível.
      amostra: estouram.sort((a, b) => b.rolagemX - a.rolagemX).slice(0, 25),
    };
  });

  return diagnostico;
}
