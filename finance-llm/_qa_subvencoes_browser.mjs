/**
 * Validação da página «Subvenções públicas» (desktop + mobile).
 *
 * A página abre como **janela** do IQ OS, pelo que há dois `<main>` no
 * documento; tudo é medido no último. Os cliques nos separadores são feitos por
 * `evaluate` (o gestor de janelas deixa o botão coberto e o clique por
 * *hit-testing* expira).
 */
const TOKEN =
  "eyJzaWQiOiJhNjljZTlhYTdjMTczMmJmMmI0NjBkY2VkZDc0ZWMxNWMyNzU3NmJiM2YwY2YxZTQiLCJzdWIiOiIzYjFmZjQxNzdiOWFmNDhjNDAwYzM1YjFiMmY2NDYxOSIsImlhdCI6MTc5MTU1OTcxNCwiZXhwIjoxNzkxNjAyOTE0fQ.S6ipiSwmTqzi-abtiHfyfpt1uwN4_gqYfNzPtA70npc";

export default async function run(page, ui) {
  const resultado = {};

  await page.evaluate((t) => window.localStorage.setItem("finance-llm-token", t), TOKEN);
  await page.goto("http://127.0.0.1:4180/subvencoes?v=20261009c", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000);
  await page.waitForFunction(() => document.body.innerText.includes("Subvenções públicas"), {
    timeout: 20000,
  });
  // O painel só aparece quando a leitura e as agregações (414 mil documentos)
  // terminam: esperar pelo número em vez de dormir um tempo fixo.
  await page.waitForFunction(() => document.body.innerText.replace(/\u00a0/g, " ").includes("414 759"), {
    timeout: 120000,
  });

  const main = page.locator("main").last();
  const texto = async () => (await main.innerText()).replace(/\u00a0/g, " ");

  /** Clica num botão pelo texto, dentro do `<main>` da página. */
  const clicar = async (rotulo, contem = false) =>
    main.evaluate(
      (el, dados) => {
        const botoes = Array.from(el.querySelectorAll("button"));
        const alvo = dados.contem
          ? botoes.find((b) => (b.textContent || "").includes(dados.rotulo))
          : botoes.find((b) => (b.textContent || "").trim() === dados.rotulo);
        if (!alvo) return false;
        alvo.click();
        return true;
      },
      { rotulo, contem }
    );

  const medir = () =>
    page.evaluate(() => {
      const todos = Array.from(document.querySelectorAll("main"));
      const el = todos[todos.length - 1];
      const dialogo = el ? el.closest('[role="dialog"]') : null;
      const caixa = dialogo ? dialogo.getBoundingClientRect() : el ? el.getBoundingClientRect() : null;
      const grelhas = el ? Array.from(el.querySelectorAll("div.grid")) : [];
      const colunas = grelhas.map((g) => getComputedStyle(g).gridTemplateColumns.split(" ").length);
      return {
        mains: todos.length,
        viewport: window.innerWidth,
        docScrollWidth: document.documentElement.scrollWidth,
        paginaScrollWidth: el ? el.scrollWidth : 0,
        paginaClientWidth: el ? el.clientWidth : 0,
        janelaLargura: caixa ? Math.round(caixa.width) : null,
        colunasGrelhas: colunas.slice(0, 6),
        temScrollHorizontal: document.documentElement.scrollWidth > window.innerWidth + 1,
      };
    });

  // O cabeçalho da página é irmão do `<main>`: o título mede-se no documento.
  const corpo = async () => (await page.locator("body").innerText()).replace(/\u00a0/g, " ");

  // ---------------------------------------------------------------- painel
  let t = await texto();
  resultado.painel = {
    titulo: (await corpo()).includes("Subvenções públicas"),
    kpiMontante: /18,9\d* mil M€/.test(t),
    kpiRegistos: /414\s?759/.test(t),
    kpiBeneficiarios: /105\s?983/.test(t),
    kpiEntidades: /\b931\b/.test(t),
    cartoesPorAno: (t.match(/ver registos/g) || []).length,
    tem2024e2025: /2024/.test(t) && /2025/.test(t),
    topEntidades: t.includes("Quem mais atribuiu"),
    topBeneficiarios: t.includes("Quem mais recebeu"),
    decisoesPorMes: t.includes("Decisões por mês"),
    tipoBeneficiario: t.includes("Tipo de beneficiário"),
    resumoTexto: t.split("\n").filter(Boolean).slice(0, 30).join(" | ").slice(0, 700),
  };

  resultado.amostraClicada = await clicar("ver amostra lida do disco", true);
  await page.waitForTimeout(2500);
  t = await texto();
  resultado.amostraDisco = {
    visivel: t.includes("Amostra de"),
    texto: (t.match(/Amostra de [^\n]{0,110}/) || [""])[0],
  };

  // -------------------------------------------------------------- pesquisa
  await clicar("Pesquisa");
  await page.waitForTimeout(1500);
  await main.locator("#subv-nif-ent").fill("500051054");
  await clicar("Pesquisar", true);
  await page.waitForTimeout(3500);

  t = await texto();
  resultado.pesquisa = {
    temKpis: t.includes("Registos") && t.includes("Montante"),
    mostra428: /\b428\b/.test(t),
    entidadeNosResultados: t.includes("MUNICÍPIO DE ALMADA"),
    resumoFiltro: t.includes("Resumo do filtro"),
    paginacao: (t.match(/página \d+ de \d+/) || [""])[0],
    primeirasLinhas: t.split("\n").filter(Boolean).slice(0, 26).join(" | ").slice(0, 700),
  };

  // --------------------------------------------------------------- detalhe
  const cartoes = main.locator("button").filter({ hasText: /lista 20\d\d/ });
  resultado.cartoesNaLista = await cartoes.count();
  if (resultado.cartoesNaLista > 0) {
    await cartoes.first().click({ force: true });
    await page.waitForTimeout(1200);
    t = await texto();
    resultado.detalhe = {
      aberto: t.includes("REGISTO") && t.includes("MONTANTE"),
      temFinalidade: t.includes("FINALIDADE"),
      temFundamento: t.includes("FUNDAMENTO LEGAL"),
      temFichaBeneficiario: t.includes("abrir ficha do beneficiário"),
      temFichaEntidade: t.includes("abrir ficha da entidade"),
      texto: t.split("\n").filter(Boolean).slice(-24).join(" | ").slice(0, 600),
    };
  }

  // ------------------------------------------------- ficha do beneficiário
  await clicar("Ficha");
  await page.waitForTimeout(1200);
  await clicar("Recebeu");
  await page.waitForTimeout(600);
  await main.locator("#subv-ficha-nif").fill("510557260");
  await clicar("Abrir ficha", true);
  await page.waitForTimeout(3000);
  t = await texto();
  resultado.fichaBeneficiario = {
    aberta: t.includes("ACADEMIA SHOWIT"),
    nif: t.includes("510557260"),
    temPorAno: t.includes("Por ano de listagem"),
    temEntidades: t.includes("Entidades que atribuíram"),
    total: (t.match(/TOTAL[^\n]{0,44}/) || [""])[0],
  };

  // -------------------------------------------------- ficha da entidade
  await clicar("Atribuiu");
  await page.waitForTimeout(600);
  await main.locator("#subv-ficha-nif").fill("500051054");
  await clicar("Abrir ficha", true);
  await page.waitForTimeout(3000);
  t = await texto();
  resultado.fichaEntidade = {
    aberta: t.includes("MUNICÍPIO DE ALMADA"),
    temBeneficiarios: t.includes("Beneficiários"),
    temPorAno: t.includes("Por ano de listagem"),
    total: (t.match(/TOTAL[^\n]{0,44}/) || [""])[0],
    limite: (t.match(/A mostrar \d+ de [\d\s]{0,12}registos/) || [""])[0],
  };

  // -------------------------------------------------------------- ficheiros
  await clicar("Ficheiros");
  await page.waitForTimeout(1800);
  t = await texto();
  resultado.ficheiros = {
    pasta: t.includes("data\\subvencoes") || t.includes("data/subvencoes"),
    temBotaoLer: t.includes("Ler pasta") && t.includes("Reler tudo"),
    temBotaoIndexar: t.includes("Indexar") && t.includes("Reindexar"),
    ficheirosPorAno: t.includes("Ficheiros por ano") && t.includes("2024") && t.includes("2025"),
    lotesLidos: t.includes("Lotes lidos"),
    registosLidos: /414\s?759/.test(t),
    indexados: t.includes("indexados"),
    linhas: t.split("\n").filter(Boolean).slice(0, 34).join(" | ").slice(0, 900),
  };

  // ------------------------------------------------- desktop / mobile
  resultado.desktop = await medir();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(1500);
  await clicar("Painel");
  await page.waitForTimeout(2000);
  t = await texto();
  resultado.mobile = await medir();
  resultado.mobile.tituloVisivel = (await corpo()).includes("Subvenções públicas");
  resultado.mobile.kpisVisiveis = /414\s?759/.test(t);

  await clicar("Pesquisa");
  await page.waitForTimeout(3000);
  resultado.mobilePesquisa = await medir();

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.waitForTimeout(800);
  return resultado;
}
