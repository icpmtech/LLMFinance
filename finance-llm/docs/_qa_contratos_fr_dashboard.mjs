export default async function run(page, ui) {
  // Esperar que a app monte (render client-side)
  await page.waitForTimeout(1200);
  const snap0 = await ui.snapshot({ full: true });

  // Procurar a ligação/módulo de Contratos França no catálogo/barra
  const hasFr = snap0.includes("Contratos FR") || snap0.includes("contratos-fr");
  if (!hasFr) {
    return { error: "Módulo Contratos França não aparece no catálogo inicial", snap: snap0.slice(0, 2000) };
  }

  // Navegar diretamente para a dashboard
  await page.goto("http://localhost:8002/?v=" + Date.now() + "#view=contratos-fr-dashboard");
  await page.waitForTimeout(1500);

  const snap = await ui.snapshot({ full: true });
  const checks = {
    total: snap.includes("contratos") || snap.includes("Total") || snap.includes("valor"),
    formePrix: snap.includes("Forma de preço") || snap.includes("Forfaitaire") || snap.includes("Unitaire"),
    localizacao: snap.includes("Tipos de localização") || snap.includes("Códigos de execução") || snap.includes("Code département"),
  };

  return { checks, snapFragment: snap.slice(0, 2500) };
}
