/**
 * Diagnóstico do estouro horizontal a 390 px.
 *
 * Em vez de listar os 120 descendentes que estouram (efeito em cascata), lista só
 * as **fontes**: os elementos cuja largura excede a moldura da página e cujo pai
 * ainda cabe. São esses que têm de ser corrigidos.
 */
const TOKEN =
  "eyJzaWQiOiIyNzNiM2FhNWU2MDhhYWQzZDdhZWY2YTg3YmVkZDAyYzAyODgzYmVmNTYwMTRjMmIiLCJzdWIiOiIzYjFmZjQxNzdiOWFmNDhjNDAwYzM1YjFiMmY2NDYxOSIsImlhdCI6MTc5MTcxMDM5NCwiZXhwIjoxNzkxNzUzNTk0fQ.shle-ZAEx1KiQFsps9CBhFROKTW-k1JwXgIefyhp720";

export default async function run(page) {
  await page.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), TOKEN);
  await page.goto("http://127.0.0.1:4180/subvencoes?v=diag5", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000);
  await page.waitForFunction(() => document.body.innerText.includes("Subvenções públicas"), null, {
    timeout: 30000,
  });
  // Esperar pelo fim do carregamento (os cartões por ano só existem com dados).
  await page.waitForFunction(
    () => {
      const mains = Array.from(document.querySelectorAll("main"));
      const el = mains[mains.length - 1];
      const t = el ? el.innerText : "";
      return t.includes("ver registos") && !t.includes("A carregar");
    },
    null,
    { timeout: 90000 }
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(2500);

  const medir = () =>
    page.evaluate(() => {
      const mains = Array.from(document.querySelectorAll("main"));
      const raiz = mains[mains.length - 1];
      if (!raiz) return { erro: "sem main" };
      const R = raiz.getBoundingClientRect();
      const descrever = (el) => {
        const c = el.getBoundingClientRect();
        return {
          tag: el.tagName,
          cls: (el.className || "").toString().replace(/\s+/g, " ").slice(0, 130),
          texto: (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 60),
          largura: Math.round(c.width),
          direita: Math.round(c.right - R.right),
          rolagemX: Math.round(el.scrollWidth - el.clientWidth),
          scrollW: el.scrollWidth,
          clientW: el.clientWidth,
        };
      };
      const estouram = [];
      raiz.querySelectorAll("*").forEach((el) => {
        const c = el.getBoundingClientRect();
        if (c.width === 0 && c.height === 0) return;
        const excede = c.right - R.right;
        const rola = el.scrollWidth - el.clientWidth;
        if (excede > 2 || rola > 2) estouram.push({ el, excede, rola });
      });
      const fontes = estouram
        .filter((o) => {
          const pai = o.el.parentElement;
          if (!pai || pai === raiz) return true;
          return pai.getBoundingClientRect().right - R.right <= 2;
        })
        .map((o) => descrever(o.el))
        .sort((a, b) => b.rolagemX + b.direita - (a.rolagemX + a.direita))
        .slice(0, 14);
      return {
        viewport: window.innerWidth,
        raiz: { largura: Math.round(R.width), scrollW: raiz.scrollWidth, clientW: raiz.clientWidth },
        totalEstouram: estouram.length,
        fontes,
      };
    });

  const painel = await medir();

  // Pesquisa: mesmo teste, no separador com os filtros e a lista.
  await page.evaluate(() => {
    const mains = Array.from(document.querySelectorAll("main"));
    const el = mains[mains.length - 1];
    const b = Array.from(el.querySelectorAll("button")).find((x) => x.textContent.trim() === "Pesquisa");
    b?.click();
  });
  await page.waitForTimeout(3500);
  const pesquisa = await medir();

  await page.setViewportSize({ width: 1280, height: 800 });
  return { painel, pesquisa };
}
