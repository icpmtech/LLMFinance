"""Sonda do módulo Lorenz contra o Elasticsearch real (mede tempos e cobertura).

Uso: python _probe_lorenz.py [area] [ano_de] [ano_ate]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api import lorenz_service as lz  # noqa: E402


def main() -> None:
    area = sys.argv[1] if len(sys.argv) > 1 else "medicamentos"
    ano_de = int(sys.argv[2]) if len(sys.argv) > 2 else 2022
    ano_ate = int(sys.argv[3]) if len(sys.argv) > 3 else 2026

    escopo = lz.escopo(area=area, ano_de=ano_de, ano_ate=ano_ate)
    print(f"== escopo {area} {ano_de}-{ano_ate} prefixos={escopo['cpv_prefixos']}")

    marca = time.time()
    serie = lz.serie(escopo)
    print(f"serie: {round(time.time() - marca, 1)}s docs={serie.get('total_documentos')} periodos={len(serie.get('periodos') or [])} erro={serie.get('erro')}")
    for periodo in (serie.get("periodos") or [])[-3:]:
        print(
            "   ",
            periodo["periodo"],
            f"contratos={periodo['contratos']}",
            f"valor={periodo['valor']:,.0f}",
            f"compradores={periodo['compradores']}",
            f"fornecedores={periodo['fornecedores']}",
            f"quota_top1={periodo['quota_top1']:.3f}",
            f"hhi={periodo['hhi_top']:.3f}",
            f"taxa_ajuste={periodo['taxa_ajuste_direto']:.2f}",
        )

    marca = time.time()
    dados = lz.matriz_dependencia(escopo)
    print(
        f"matriz_dependencia: {round(time.time() - marca, 1)}s compradores={dados['totais']['compradores']} "
        f"fornecedores={dados['totais']['fornecedores']} arestas={dados['totais']['arestas']} "
        f"valor_coberto={dados['totais']['valor_coberto']:,.0f}"
    )
    for comprador in dados["compradores"][:3]:
        print(
            "   ",
            comprador["nome"][:42],
            f"valor={comprador['valor']:,.0f}",
            f"quota_top1={comprador['quota_top1']:.3f}",
            f"n_forn_top={comprador['n_fornecedores_top']}",
            f"cpvs={len(comprador['cpvs'])}",
            "top=",
            (comprador["fornecedores"][0]["nome"][:28] if comprador["fornecedores"] else "—"),
        )

    marca = time.time()
    cpvs = lz.matriz_cpv(escopo)
    print(f"matriz_cpv: {round(time.time() - marca, 1)}s classes={len(cpvs.get('classes') or [])}")
    for classe in (cpvs.get("classes") or [])[:4]:
        print(
            "   ",
            classe["classe"],
            f"valor={classe['valor']:,.0f}",
            f"forn={len(classe.get('fornecedores') or [])}",
            f"quota_top1={classe.get('quota_top1', 0):.3f}",
            "dominante=",
            ((classe.get("fornecedores") or [{}])[0].get("nome") or "—")[:30],
        )

    dep = lz.dependencias(dados)
    print(f"alertas: {len(dep['alertas'])}")
    for alerta in dep["alertas"][:4]:
        print("   ", alerta["tipo"], "|", alerta["entidade"][:40], "|", alerta["medida"][:80])

    amplificadores = lz.ranking_amplificadores(dados, cpvs=cpvs, topo=5)
    print("amplificadores:")
    for linha in amplificadores:
        print(
            "   ",
            (linha["nome"] or "—")[:36],
            f"alcance={linha['alcance']:.2f}",
            f"exposicao={linha['exposicao']:.2f}",
            f"dificuldade={linha['dificuldade_media']:.2f}",
            f"amplificacao={linha['amplificacao']:.4f}",
        )

    if amplificadores:
        marca = time.time()
        resultado = lz.propagar(dados, fornecedor_nif=amplificadores[0]["nif"], atraso_dias=30, cpvs=cpvs)
        print(
            f"propagar(30d): {round(time.time() - marca, 1)}s afetados={len(resultado.get('diretos') or [])} "
            f"impacto={resultado.get('impacto_total_estimado', 0):,.0f} novos_fragies={len(resultado.get('novos_fragies') or [])}"
        )
        for linha in (resultado.get("diretos") or [])[:3]:
            print(
                "   ",
                (linha["comprador_nome"] or "—")[:34],
                f"quota={linha['quota']:.2f}",
                f"exposto={linha['exposto']:,.0f}",
                f"sobrecusto={linha['sobrecusto_estimado']:,.0f}",
                f"dificuldade={linha['dificuldade_substituicao']:.2f}",
                f"alt={len(linha['alternativas'])}",
            )
        print("   cenarios:", [(c["atraso_dias"], round(c["impacto_total"]), c["criticos"]) for c in (lz.cenarios_atraso(dados, fornecedor_nif=amplificadores[0]["nif"], cpvs=cpvs).get("cenarios") or [])])
        ev = lz.evidencias(escopo, fornecedor_nif=amplificadores[0]["nif"], limite=3)
        print(f"   evidencias: total={ev.get('total')}")
        for item in ev.get("itens") or []:
            print("      ", item["idcontrato"], (item.get("objeto") or "")[:50], f"{item['valor']:,.0f}", item.get("adjudicante", "")[:24])

    estado = lz.estado_da_serie(serie["periodos"])
    params = lz.estimar_parametros(serie["periodos"])
    mapa = lz.ajustar_mapa_linear(estado["coordenadas"])
    print("estado normalizado (ultimos):", [[round(v, 3) for v in linha] for linha in estado["coordenadas"][-3:]])
    print("parametros:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in params.items() if k in ("sigma", "beta", "rho", "rho_critico", "margem", "regime", "autocorrelacao_valor")})
    print("mapa:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in mapa.items() if k in ("r2", "raio_espectral", "pares", "disponivel")})
    if mapa.get("disponivel"):
        div = lz.divergencia_mapa(estado["coordenadas"][-1], mapa["A"], mapa["b"], perturbacao=1e-3, passos=6, direcoes=12)
        print("divergencia:", [round(v, 5) for v in div["D"]], "lambda=", round(div["lambda_empirico"], 4), div["regime"])
    marca = time.time()
    lyap = lz.lyapunov_maximo([1.0, 1.0, 1.0], params.get("sigma", 10.0), params.get("rho", 28.0), params.get("beta", 8 / 3), perturbacao=1e-4, passos=2000)
    print(f"lyapunov lorenz: {round(time.time() - marca, 1)}s lambda={lyap['lambda']:.4f} regime={lyap['regime']}")

    marca = time.time()
    completo = lz.panorama(escopo, incluir_grafo=True)
    print(f"PANORAMA completo: {round(time.time() - marca, 1)}s tempos={completo.get('tempos')} duracao={completo.get('duracao_s')}")
    print("kpis:", json.dumps(completo.get("kpis"), ensure_ascii=False, default=str)[:1200])
    print("alertas por origem:", completo["dependencias"].get("alertas_por_origem"))
    for alerta in (completo["dependencias"].get("alertas") or [])[:5]:
        print("   ", alerta.get("origem"), "|", alerta.get("severidade"), "|", str(alerta.get("entidade"))[:40], "|", str(alerta.get("medida"))[:90])
    print("grafo:", len((completo.get("grafo") or {}).get("nodes") or []), "nos,", len((completo.get("grafo") or {}).get("edges") or []), "arestas")


if __name__ == "__main__":
    main()
