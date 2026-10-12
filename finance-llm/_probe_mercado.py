"""Sonda do módulo de mercado contra o Elasticsearch real (cobertura CAE e tempos).

Uso: python _probe_mercado.py [area] [ano_de] [ano_ate]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api import mercado_service as mk  # noqa: E402


def main() -> None:
    area = sys.argv[1] if len(sys.argv) > 1 else "medicamentos"
    ano_de = int(sys.argv[2]) if len(sys.argv) > 2 else 2023
    ano_ate = int(sys.argv[3]) if len(sys.argv) > 3 else 2026
    escopo = mk.lz.escopo(area=area, ano_de=ano_de, ano_ate=ano_ate)
    print(f"== escopo {area} {ano_de}-{ano_ate} prefixos={escopo['cpv_prefixos']}")

    marca = time.time()
    mercados = mk.mercados(escopo, top=4)
    print(f"mercados: {round(time.time() - marca, 1)}s docs={mercados.get('total_documentos')}")
    for mercado in mercados["mercados"]:
        qualidade = mercado["qualidade"]
        print(
            f"   CPV {mercado['cpv_classe']} valor={mercado['valor']:,.0f} contratos={mercado['contratos']} "
            f"empresas={mercado['empresas_analisadas']} com_cae={mercado['empresas_com_cae']} "
            f"compativeis={mercado['empresas_compativeis']} cobertura_cae={mercado['cobertura_cae']:.0%} "
            f"qualidade={qualidade['grau']} hhi={mercado['hhi']:.3f}"
        )
        for empresa in mercado["empresas"][:4]:
            print(
                "      ",
                (empresa["nome"] or "—")[:38],
                f"valor={empresa['valor']:,.0f}",
                f"quota={empresa['quota']:.1%}",
                f"CAE={empresa['cae_principal'] or '—'}",
                f"compat={empresa['compatibilidade']}",
                f"({(empresa['cae_label'] or '')[:34]})",
            )

    if not mercados["mercados"]:
        print("sem mercados — termina")
        return
    classe = mercados["mercados"][0]["cpv_classe"]

    marca = time.time()
    bench = mk.benchmark(escopo, cpv=classe, limite=6)
    print(f"benchmark (CPV {classe}): {round(time.time() - marca, 1)}s mercado={bench['mercado']['valor']:,.0f} empresas={len(bench['empresas'])}")
    print("   cabeçalho:", " | ".join(["empresa", "contratos", "valor", "quota", "entidades", "maior ent.", "D_i", "evolução", "CAE", "compat"]))
    for empresa in bench["empresas"]:
        maior = empresa["maior_entidade"] or {}
        evolucao = empresa["evolucao"] or {}
        print(
            "   ",
            (empresa["nome"] or "—")[:30].ljust(30),
            str(empresa["contratos"]).rjust(6),
            f"{empresa['valor']:>14,.0f}",
            f"{empresa['quota']:>6.1%}",
            str(empresa["entidades_distintas"]).rjust(5),
            f"{maior.get('quota', 0):>5.0%}",
            f"{(empresa['dependencia'] or {}).get('hhi', 0):>6.3f}",
            (f"{evolucao.get('variacao') * 100:+.0f}%" if evolucao.get("variacao") is not None else "   —").rjust(7),
            (empresa["cae_principal"] or "—").rjust(6),
            str(empresa["compatibilidade"])[:11].ljust(11),
        )
        if empresa["alertas"]:
            print("        alertas:", "; ".join(f"{a['tipo']} ({a['detalhe']})" for a in empresa["alertas"]))
    for aviso in bench["avisos"]:
        print("   aviso:", aviso)

    marca = time.time()
    deps = mk.dependencias(escopo, nifs=[e["nif"] for e in bench["empresas"][:4]])
    print(f"dependencias: {round(time.time() - marca, 1)}s totais={deps['totais']}")
    for entidade in deps["entidades"][:3]:
        print(
            "   entidade",
            (entidade["nome"] or "—")[:34],
            f"valor={entidade['valor']:,.0f}",
            f"fornecedores={entidade['fornecedores']}",
            f"maior={entidade['dependencia']['maior_quota']:.0%}",
            f"critico={entidade['critico']}",
            "principal:",
            ((entidade.get("maior_fornecedor") or {}).get("nome") or "—")[:28],
        )

    marca = time.time()
    grafo = mk.grafo_temporal(escopo, nifs=[e["nif"] for e in bench["empresas"][:3]], contratos=6)
    tipos: dict = {}
    for no in grafo["nodes"]:
        tipos[no["dimension"]] = tipos.get(no["dimension"], 0) + 1
    print(f"grafo: {round(time.time() - marca, 1)}s nos={len(grafo['nodes'])} {tipos} arestas={len(grafo['edges'])}")

    marca = time.time()
    cenarios = mk.cenarios(escopo, nif=bench["empresas"][0]["nif"])
    print(f"cenarios: {round(time.time() - marca, 1)}s duracao={cenarios['duracao_s']}s")
    for evento in cenarios["eventos"]:
        if not evento.get("disponivel"):
            print("   ", evento["evento"], "-> indisponível:", evento.get("motivo"))
            continue
        medicao = evento["medicao"]
        resumo = {chave: medicao.get(chave) for chave in ("quota_do_valor", "exposicao", "valor", "contratos", "delta_valor", "quota_estimada_do_entrante") if chave in medicao}
        if "estrito" in medicao:
            estrito, estimado = medicao["estrito"], medicao["estimado"]
            resumo["estrito"] = f"{estrito['contratos']} contratos / {estrito['valor']:,.0f} €"
            resumo["estimado"] = f"{estimado['contratos']} contratos / {estimado['valor']:,.0f} €"
            resumo["janela"] = medicao.get("janela")
        if evento["evento"] == "perda_maior_comprador":
            resumo["dependencia_depois_hhi"] = (medicao.get("dependencia_depois") or {}).get("hhi")
        if evento["evento"] == "diversificacao":
            resumo["dependencia_simulada_hhi"] = (medicao.get("dependencia_simulada") or {}).get("hhi")
        print("   ", evento["evento"], "->", json.dumps(resumo, ensure_ascii=False, default=str)[:220])

    marca = time.time()
    sens = cenarios["sensibilidade"]
    print(f"sensibilidade: {round(time.time() - marca, 1)}s disponivel={sens.get('disponivel')}")
    if sens.get("disponivel"):
        params = sens["parametros"]
        print(
            "   parametros:",
            f"sigma={params['sigma']:.2f} beta={params['beta']:.2f} rho={params['rho']:.1f} rho_crit={params['rho_critico']:.1f} "
            f"margem={params['margem']:.2f} regime={params['regime']}",
        )
        print("   mapa:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in sens["mapa"].items() if k in ("disponivel", "r2", "raio_espectral", "pares")})
        print("   divergencia lambda:", round(sens["divergencia"].get("lambda_empirico", 0), 4), sens["divergencia"].get("regime"))
        print("   lorenz lambda:", round(sens["lorenz"]["lyapunov"]["lambda"], 4), sens["lorenz"]["lyapunov"]["regime"])


if __name__ == "__main__":
    main()
