/**
 * **Marca das empresas no benchmark** — sites e logótipos.
 *
 * O backend descobre o site oficial e o logótipo de cada empresa (pesquisa web,
 * validação por HTTP e arbitragem por IA). Aqui:
 *
 * 1. lê-se primeiro o que já está em cache no servidor (resposta imediata, é o
 *    que o grafo mostra ao abrir);
 * 2. o que falta é resolvido em **lotes pequenos**, em série, actualizando o
 *    ecrã à medida que chega — o utilizador vê os logótipos a aparecer em vez de
 *    esperar por todos.
 *
 * O resultado fica também num cache em memória do browser, para mudar de página
 * e voltar não repetir nem os pedidos locais.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { EmpresaPerfil, EmpresaPerfilAlvo } from "../../empresasPerfil";
import { getPerfisEmpresas, resolverPerfisEmpresas } from "../../empresasPerfil";

/** Cache em memória (NIF/nome → perfil), partilhado por todos os componentes. */
const cache = new Map<string, EmpresaPerfil>();
/** Empresas já resolvidas nesta sessão (mesmo sem site, para não repetir). */
const tentados = new Set<string>();

export function chaveEmpresa(alvo: { nif?: string | null; nome?: string | null }): string {
  const nif = String(alvo.nif || "").replace(/\D+/g, "");
  if (nif.length >= 6) return nif;
  const nome = String(alvo.nome || "").trim().toLowerCase();
  return nome ? `n:${nome}` : "";
}

/** Perfil já conhecido (cache do browser), sem pedidos. */
export function perfilEmCache(alvo: { nif?: string | null; nome?: string | null }): EmpresaPerfil | undefined {
  const chave = chaveEmpresa(alvo);
  if (chave && cache.has(chave)) return cache.get(chave);
  const porNome = cache.get(`n:${String(alvo.nome || "").trim().toLowerCase()}`);
  return porNome;
}

export function forcarPerfil(alvo: { nif?: string | null; nome?: string | null }): void {
  const chave = chaveEmpresa(alvo);
  if (chave) {
    cache.delete(chave);
    tentados.delete(chave);
  }
}

export interface EstadoPerfis {
  /** Perfis disponíveis (cache do servidor + já resolvidos). */
  perfis: Record<string, EmpresaPerfil>;
  /** Quantas empresas estão a ser procuradas neste momento. */
  aResolver: number;
  /** Progresso da resolução automática (empresas com marca / total pedido). */
  progresso: { total: number; concluidos: number };
  /** Último erro (mostrado de forma discreta na interface). */
  erro?: string;
  /** Volta a procurar (ignorando o cache do servidor). */
  repetir: () => void;
}

/**
 * Marcas das empresas de uma lista.
 *
 * @param alvos empresas a identificar (NIF é suficiente)
 * @param opcoes.ativo  desliga a resolução automática (por exemplo para poupar
 *                      pedidos enquanto o utilizador configura o segmento)
 * @param opcoes.pais   país por omissão quando o alvo não traz o seu
 */
export function usePerfisEmpresas(
  alvos: EmpresaPerfilAlvo[],
  opcoes: { ativo?: boolean; pais?: "pt" | "es" | "fr"; usarIa?: boolean } = {},
): EstadoPerfis {
  const ativo = opcoes.ativo ?? true;
  const pais = opcoes.pais || "pt";
  const usarIa = opcoes.usarIa ?? true;

  const [perfis, setPerfis] = useState<Record<string, EmpresaPerfil>>({});
  const [aResolver, setAResolver] = useState(0);
  const [concluidos, setConcluidos] = useState(0);
  const [erro, setErro] = useState<string | undefined>();
  const [repeticao, setRepeticao] = useState(0);
  const vivo = useRef(true);

  // A lista de alvos é reconstruída a cada render: a chave evita ciclos.
  const lista = useMemo(() => {
    const vistos = new Map<string, EmpresaPerfilAlvo>();
    for (const alvo of alvos) {
      const chave = chaveEmpresa(alvo);
      if (!chave || vistos.has(chave)) continue;
      vistos.set(chave, { nif: alvo.nif, nome: alvo.nome, pais: alvo.pais || pais });
    }
    return Array.from(vistos.entries());
  }, [alvos, pais]);

  const assinatura = useMemo(() => lista.map(([chave]) => chave).join("|"), [lista]);

  useEffect(() => {
    vivo.current = true;
    return () => {
      vivo.current = false;
    };
  }, []);

  const publicar = useCallback((entradas: Array<[string, EmpresaPerfil]>) => {
    if (!vivo.current) return;
    setPerfis((anterior) => {
      const seguinte = { ...anterior };
      for (const [chave, perfil] of entradas) seguinte[chave] = perfil;
      return seguinte;
    });
  }, []);

  useEffect(() => {
    if (!assinatura) return;
    let cancelado = false;

    const correr = async () => {
      const chaves = lista.map(([chave]) => chave);
      // 1) cache do browser
      const doBrowser = new Map<string, EmpresaPerfil>();
      for (const [chave, alvo] of lista) {
        const guardado = perfilEmCache(alvo);
        if (guardado) doBrowser.set(chave, guardado);
      }
      if (doBrowser.size) publicar(Array.from(doBrowser.entries()));
      const jaEmCache = new Set(doBrowser.keys());

      if (!ativo) {
        if (!cancelado) setConcluidos(jaEmCache.size);
        return;
      }

      // 2) cache do servidor (rápido, sem rede externa)
      const faltam = chaves.filter((chave) => !jaEmCache.has(chave));
      if (!cancelado) setConcluidos(jaEmCache.size);
      if (!faltam.length) {
        setAResolver(0);
        return;
      }
      let pendentes = [...faltam];
      try {
        const doServidor = await getPerfisEmpresas(pendentes);
        if (cancelado) return;
        const achados: Array<[string, EmpresaPerfil]> = [];
        for (const [chave, perfil] of Object.entries(doServidor)) {
          cache.set(chave, perfil);
          achados.push([chave, perfil]);
        }
        publicar(achados);
        const respondidas = new Set(Object.keys(doServidor));
        pendentes = pendentes.filter((chave) => !respondidas.has(chave));
        if (!cancelado) setConcluidos(jaEmCache.size + achados.length);
      } catch (excecao) {
        if (!cancelado) setErro((excecao as Error).message);
        return;
      }

      // 3) resolver o que falta, em lotes pequenos — em série para não saturar
      const porResolver = pendentes.filter((chave) => !tentados.has(chave));
      if (!porResolver.length) {
        setAResolver(0);
        return;
      }
      const porChave = new Map(lista);
      const LOTE = 4;
      if (!cancelado) setAResolver(porResolver.length);
      for (let inicio = 0; inicio < porResolver.length; inicio += LOTE) {
        if (cancelado) return;
        const lote = porResolver.slice(inicio, inicio + LOTE);
        const pedido: EmpresaPerfilAlvo[] = lote.map((chave) => {
          const alvo = porChave.get(chave) || {};
          return { nif: alvo.nif, nome: alvo.nome, pais: alvo.pais || pais };
        });
        try {
          const resposta = await resolverPerfisEmpresas(pedido, { pais, usarIa });
          if (cancelado) return;
          const novos: Array<[string, EmpresaPerfil]> = [];
          resposta.perfis.forEach((perfil, indice) => {
            const chave = chaveEmpresa({ nif: perfil?.nif, nome: perfil?.nome }) || lote[indice];
            if (!chave) return;
            if (perfil?.erro) {
              // Falhou por rede: não marca como tentado, para se tentar de novo.
              return;
            }
            cache.set(chave, perfil);
            tentados.add(chave);
            novos.push([chave, perfil]);
          });
          publicar(novos);
          setAResolver((valor) => Math.max(0, valor - lote.length));
          setConcluidos((valor) => valor + lote.length);
        } catch (excecao) {
          if (!cancelado) setErro((excecao as Error).message);
          break;
        }
      }
      if (!cancelado) setAResolver(0);
    };

    void correr();
    return () => {
      cancelado = true;
    };
  }, [assinatura, ativo, pais, usarIa, repeticao, lista, publicar]);

  const repetir = useCallback(() => {
    for (const [chave, alvo] of lista) {
      tentados.delete(chave);
      forcarPerfil(alvo);
    }
    setPerfis({});
    setConcluidos(0);
    setErro(undefined);
    setRepeticao((valor) => valor + 1);
  }, [lista]);

  return { perfis, aResolver, progresso: { total: lista.length, concluidos }, erro, repetir };
}

/** Logótipo de uma empresa a partir dos perfis já carregados. */
export function logoDe(
  perfis: Record<string, EmpresaPerfil>,
  alvo: { nif?: string | null; nome?: string | null },
): string | null {
  const chave = chaveEmpresa(alvo);
  const perfil = perfis[chave] || perfis[`n:${String(alvo.nome || "").trim().toLowerCase()}`];
  return perfil?.logo_url || null;
}

/** Site oficial de uma empresa a partir dos perfis já carregados. */
export function siteDe(
  perfis: Record<string, EmpresaPerfil>,
  alvo: { nif?: string | null; nome?: string | null },
): string | null {
  const chave = chaveEmpresa(alvo);
  const perfil = perfis[chave] || perfis[`n:${String(alvo.nome || "").trim().toLowerCase()}`];
  return perfil?.site || null;
}
