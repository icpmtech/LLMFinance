// QA temporário: abrir a ficha do contrato a partir da tabela da ficha da empresa.
export async function run(page) {
  const token = process.env.IQOS_TEST_TOKEN || "";
  await page.addInitScript((t) => {
    try {
      window.localStorage.setItem("finance-llm-token", t);
    } catch {}
  }, token);

  const largura = Number(process.env.IQOS_LARGURA || 820);
  await page.setViewportSize({ width: largura, height: 1100 });
  await page.goto(page.url(), { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(9000);

  const lerJanelas = () =>
    page.evaluate(() => {
      try {
        const bruto = JSON.parse(window.localStorage.getItem("finance-llm-windows:v1") || "{}");
        return (bruto.windows || []).map((w) => w.view);
      } catch {
        return [];
      }
    });

  const janelasAntes = await lerJanelas();

  const clicou = await page.evaluate(() => {
    const h2 = [...document.querySelectorAll("h2")].find(
      (n) => (n.textContent || "").trim() === "Contratos recentes",
    );
    const cartao = h2?.closest("div.glass-card") || h2?.parentElement?.parentElement;
    const linha = cartao?.querySelector("tbody tr");
    if (!linha) return false;
    linha.click();
    return true;
  });
  await page.waitForTimeout(6000);

  const depois = await page.evaluate(() => {
    // As janelas do gestor também usam `aria-label` com o título («Ficha do contrato»),
    // por isso a modal distingue-se pelo `aria-modal`.
    const dialogo = document.querySelector('[role="dialog"][aria-modal="true"]');
    return {
      modal: Boolean(dialogo),
      textoModal: (dialogo?.textContent || "").replace(/\s+/g, " ").trim().slice(0, 140),
      detalheNoDom: /Detalhe do Contrato/i.test(document.body.innerText),
    };
  });

  return { largura, janelasAntes, clicou, janelasDepois: await lerJanelas(), depois };
}
