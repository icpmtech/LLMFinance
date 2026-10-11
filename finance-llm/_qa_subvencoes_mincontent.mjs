/**
 * Diagnóstico fino: porque é que a coluna da grelha mede 668 px a 390 px?
 *
 * Para um cartão do painel, imprime a cadeia de ancestrais e, dentro dele, os
 * elementos cuja largura mínima (`min-content`) é grande — que são os que
 * impõem a largura da coluna.
 */
const TOKEN = process.env.QA_TOKEN || "";

export default async function run(page) {
  await page.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), TOKEN);
  await page.goto("http://127.0.0.1:4180/subvencoes?v=diag6", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000);
  await page.waitForFunction(() => document.body.innerText.includes("Subvenções públicas"), null, {
    timeout: 30000,
  });
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

  return page.evaluate(() => {
    const mains = Array.from(document.querySelectorAll("main"));
    const raiz = mains[mains.length - 1];

    // Largura mínima real de um elemento, medida no browser (com o elemento
    // fora do fluxo, com `width: min-content`).
    const minContent = (el) => {
      const pai = el.parentElement;
      const marcador = document.createComment("medir");
      pai.insertBefore(marcador, el);
      const antes = {
        largura: el.style.width,
        posicao: el.style.position,
        flutuacao: el.style.float,
      };
      el.style.position = "absolute";
      el.style.width = "min-content";
      const medida = Math.round(el.getBoundingClientRect().width);
      el.style.width = antes.largura;
      el.style.position = antes.posicao;
      el.style.float = antes.flutuacao;
      pai.removeChild(marcador);
      return medida;
    };

    const cartao = Array.from(raiz.querySelectorAll("div")).find((d) =>
      (d.className || "").toString().includes("rounded-2xl") && (d.textContent || "").includes("Quem mais atribuiu")
    );
    if (!cartao) return { erro: "cartão não encontrado" };

    const cadeia = [];
    let atual = cartao;
    while (atual && atual !== raiz.parentElement) {
      const c = atual.getBoundingClientRect();
      const est = getComputedStyle(atual);
      cadeia.push({
        tag: atual.tagName,
        cls: (atual.className || "").toString().replace(/\s+/g, " ").slice(0, 110),
        largura: Math.round(c.width),
        minWidth: est.minWidth,
        display: est.display,
        gridCols: est.gridTemplateColumns.slice(0, 60),
      });
      atual = atual.parentElement;
    }

    // Os descendentes do cartão com maior largura mínima.
    const largos = [];
    cartao.querySelectorAll("*").forEach((el) => {
      const c = el.getBoundingClientRect();
      if (c.width === 0) return;
      largos.push({
        tag: el.tagName,
        cls: (el.className || "").toString().replace(/\s+/g, " ").slice(0, 110),
        texto: (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 50),
        largura: Math.round(c.width),
        minContent: minContent(el),
        whiteSpace: getComputedStyle(el).whiteSpace,
        minWidth: getComputedStyle(el).minWidth,
      });
    });

    return {
      cartaoLargura: Math.round(cartao.getBoundingClientRect().width),
      cartaoMinContent: minContent(cartao),
      cadeia: cadeia.slice(0, 8),
      maioresMinContent: largos.sort((a, b) => b.minContent - a.minContent).slice(0, 12),
    };
  });
}
