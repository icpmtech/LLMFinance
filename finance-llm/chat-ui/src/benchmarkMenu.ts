/**
 * Entradas de menu dos **benchmarks de produtos** — uma por estudo.
 *
 * O catálogo da barra lateral (`sidebarCatalog.APP_MODULES`) é estático, mas os
 * benchmarks são criados pelos utilizadores: este módulo mantém a lista em
 * cache, avisa quem estiver a ouvir (a barra lateral re-renderiza) e é o único
 * sítio que sabe ir buscá-la à API.
 *
 * Mesmo padrão das páginas iframe (`iframePages.ts`), para a barra lateral não
 * precisar de estado próprio nem de pedidos repetidos.
 */
import { listarBenchmarks } from "./benchmarksApi";

export type BenchmarkMenuItem = {
  slug: string;
  label: string;
  hint: string;
  /** Índice próprio do benchmark no Elasticsearch. */
  index: string;
  publico: boolean;
};

let cache: BenchmarkMenuItem[] = [];
let revision = 0;
let emCurso: Promise<BenchmarkMenuItem[]> | null = null;
const ouvintes = new Set<() => void>();

function avisar() {
  revision += 1;
  ouvintes.forEach((ouvinte) => {
    try {
      ouvinte();
    } catch {
      /* um ouvinte avariado não trava os outros */
    }
  });
}

export function subscribeBenchmarkMenu(ouvinte: () => void): () => void {
  ouvintes.add(ouvinte);
  return () => ouvintes.delete(ouvinte);
}

export function getBenchmarkMenuRevision(): number {
  return revision;
}

/** Lista em cache (vazia até a primeira recolha da API). */
export function benchmarkMenuItems(): BenchmarkMenuItem[] {
  return cache;
}

/** Vai buscar a lista de benchmarks à API e avisa quem estiver a ouvir. */
export function refreshBenchmarkMenu(): Promise<BenchmarkMenuItem[]> {
  if (emCurso) return emCurso;
  emCurso = (async () => {
    try {
      const listagem = await listarBenchmarks();
      cache = (listagem.items ?? []).map((benchmark) => ({
        slug: benchmark.slug,
        label: benchmark.name,
        hint: benchmark.description || `${benchmark.stats?.products ?? 0} produtos em ${benchmark.stats?.stores ?? 0} lojas`,
        index: `finance_bench_${benchmark.slug.replace(/-/g, "_")}`,
        publico: Boolean(benchmark.public),
      }));
      avisar();
    } catch {
      /* sem rede mantém-se o que já havia: o menu não pode desaparecer */
    } finally {
      emCurso = null;
    }
    return cache;
  })();
  return emCurso;
}
