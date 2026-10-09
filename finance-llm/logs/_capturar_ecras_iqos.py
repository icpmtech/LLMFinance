"""Captura ecrãs reais do IQ OS para o PowerPoint de negócio.

Autentica-se com uma **sessão de serviço** (criada dentro do container do backend,
por isso não é preciso browser aberto nem palavra-passe), injeta o token no
`localStorage` da aplicação (`finance-llm-token`), percorre uma lista de rotas e
guarda um PNG por ecrã em `exports/business/ecras/`.

Uso::

    python logs/_capturar_ecras_iqos.py                      # tudo automático
    python logs/_capturar_ecras_iqos.py --token <TOKEN>      # token já obtido
    python logs/_capturar_ecras_iqos.py --base http://127.0.0.1:4180

O token é pedido ao container com `docker exec` (o container tem Elasticsearch e
o índice de chaves). Se o Docker não estiver a correr, nada disto funciona: passa
`--token` de uma sessão válida.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "exports" / "business" / "ecras"

# (rota, nome do ficheiro, espera extra em segundos) — rotas reais da SPA.
# A landing page é capturada à parte, **sem** sessão (é pública): visitá-la com o
# token injetado foi o que fez a aplicação voltar ao ecrã de login em várias rotas
# na passagem de 15:29 (o token era removido e as páginas seguintes caiam no login,
# todas com o mesmo tamanho de ficheiro).
ECRAS = [
    ("/contracts/dashboard", "02_dashboard_contratos", 8),
    ("/contracts/map", "03_mapa_contratos", 10),
    ("/contracts/search", "04_pesquisa_contratos", 7),
    ("/adjudicatarios", "05_adjudicatarios", 7),
    ("/empresas-iq", "06_empresas_iq", 9),
    ("/empresas-risco", "07_risco_empresas", 8),
    ("/pessoas-iq", "08_pessoas_iq", 8),
    ("/hermes", "09_hermes_ia", 7),
    ("/search360", "10_search360", 8),
    ("/visualizador", "11_visualizador_bi", 8),
    ("/world", "12_world_model", 9),
    ("/reports", "13_relatorios", 6),
    ("/shop", "14_loja", 6),
    ("/contribuintes", "15_contribuintes", 7),
    ("/crm", "16_crm", 7),
]

#: A landing page (pública) é capturada no fim, num contexto sem sessão.
ECRA_LANDING = ("/", "01_landing", 5)


def esta_autenticado(pagina) -> bool:
    """A app mostrou o formulário de entrada em vez da aplicação?"""
    try:
        return not pagina.evaluate(
            "() => !!document.querySelector(\"input[type=password]\") "
            "|| (document.body.innerText || '').includes('A validar a sess');"
        )
    except Exception:  # noqa: BLE001
        return True


def aceitar_cookies(pagina) -> bool:
    """Aceita o painel de consentimento do iubenda (vive dentro de um iframe).

    Sem isto, o modal branco da iubenda tapa o centro de **todos** os ecrãs — foi
    o que aconteceu na primeira passagem. O consentimento fica em cookie, por isso
    normalmente só é preciso à primeira navegação; ao clicar «Aceitar todos»
    guardamos as escolhas reais do utilizador em vez de esconder o painel por CSS.
    """
    for seletor in (
        "iframe[id^='iubenda']",
        "iframe[title*='iubenda']",
        "iframe[src*='iubenda']",
        "iframe[id*='iubenda']",
    ):
        try:
            quadro = pagina.frame_locator(seletor)
            if quadro.locator("body").count() == 0:
                continue
            for texto in ("Aceitar todos", "Aceitar e fechar", "Aceito", "Aceitar"):
                botao = quadro.get_by_role("button", name=texto)
                if botao.count():
                    botao.first.click(timeout=3000)
                    pagina.wait_for_timeout(700)
                    return True
        except Exception:  # noqa: BLE001 - segue para o seletor seguinte
            continue
    return False


def esconder_consentimento(pagina) -> None:
    """Reserva: se o clique falhar, esconde o painel para o ecrã ficar limpo."""
    try:
        pagina.add_style_tag(content=(
            "#iubenda-cs-banner, .iubenda-cs-container, .iubenda-cs-visible, "
            "iframe[id^='iubenda'], iframe[src*='iubenda'] { display: none !important; }"
        ))
    except Exception:  # noqa: BLE001
        pass


def token_do_container(container: str = "finance-llm-backend") -> str:
    """Cria uma sessão de serviço e devolve o token (via `docker exec`)."""
    if not shutil.which("docker"):
        return ""
    codigo = (
        "from api import auth_service;"
        "us = auth_service.list_users(1) or [];"
        "s = auth_service.create_session(us[0]) if us else {};"
        "print('TOKEN=' + str(s.get('token', '')))"
    )
    try:
        saida = subprocess.run(
            ["docker", "exec", container, "python", "-c", codigo],
            capture_output=True, text=True, timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  (sem token do container: {type(exc).__name__}: {exc})")
        return ""
    for linha in (saida.stdout or "").splitlines():
        if linha.startswith("TOKEN="):
            return linha.split("=", 1)[1].strip()
    if saida.stderr:
        print("  (stderr do container:", saida.stderr.strip()[:200], ")")
    return ""


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description="Captura ecrãs do IQ OS para o PowerPoint.")
    parser.add_argument("--base", default="http://127.0.0.1:4180", help="URL da interface")
    parser.add_argument("--token", default="", help="Token de sessão (se não vier do container)")
    parser.add_argument("--largura", type=int, default=1600)
    parser.add_argument("--altura", type=int, default=950)
    args = parser.parse_args(argv)

    token = args.token or token_do_container()
    if not token:
        print("Sem token: as páginas autenticadas vão cair no login.", file=sys.stderr)

    DESTINO.mkdir(parents=True, exist_ok=True)
    feitos: list[str] = []
    falhados: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        contexto = browser.new_context(
            viewport={"width": args.largura, "height": args.altura},
            device_scale_factor=1,
            locale="pt-PT",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
            ),
        )
        if token:
            contexto.add_init_script(
                f"try {{ window.localStorage.setItem('finance-llm-token', {json.dumps(token)}); }} catch (e) {{}}"
            )
        pagina = contexto.new_page()
        pagina.set_default_timeout(45000)
        erros: list[str] = []
        pagina.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
        consentimento_aceite = False

        for rota, nome, espera in ECRAS:
            alvo = f"{args.base}{rota}"
            try:
                pagina.goto(alvo, wait_until="load", timeout=60000)
                try:
                    pagina.wait_for_load_state("networkidle", timeout=20000)
                except Exception:  # noqa: BLE001 - SPA com polling nunca fica idle
                    pass
                pagina.wait_for_timeout(int(espera * 1000))
                # As janelas da aplicação são retomadas do `localStorage`
                # (`finance-llm-windows:v1`): sem limpar, cada rota abre mais uma e
                # os ecrãs ficam com uma pilha de janelas atrás. Mantém-se a sessão
                # e limpa-se só o layout, para cada captura mostrar **uma** janela.
                pagina.evaluate(
                    "() => { try { window.localStorage.removeItem('finance-llm-windows:v1'); } catch (e) {} }"
                )
                pagina.reload(wait_until="load", timeout=60000)
                pagina.wait_for_timeout(int(espera * 1000))
                # Consentimento (iubenda): à primeira navegação aceita-se mesmo;
                # em todas se garante que o painel não tapa o ecrã.
                if not consentimento_aceite:
                    consentimento_aceite = aceitar_cookies(pagina)
                    if consentimento_aceite:
                        print("  (consentimento iubenda aceite)")
                esconder_consentimento(pagina)
                pagina.wait_for_timeout(400)
                # Verificação: se caiu no login (a app pode limpar o token), volta a
                # injectar a sessão e recarrega a rota uma vez.
                if not esta_autenticado(pagina):
                    print(f"  ... {nome}: caiu no login, a repor a sessao")
                    pagina.evaluate(
                        "(t) => window.localStorage.setItem('finance-llm-token', t)", token
                    )
                    pagina.goto(alvo, wait_until="load", timeout=60000)
                    pagina.wait_for_timeout(int(espera * 1000))
                    esconder_consentimento(pagina)
                    if not esta_autenticado(pagina):
                        falhados.append(f"{nome} ({rota}): autenticacao")
                        print(f"  ERRO {nome:26} {rota} :: continua no login")
                        continue
                caminho = DESTINO / f"{nome}.png"
                pagina.screenshot(path=str(caminho), full_page=False)
                feitos.append(f"{nome} <- {rota}")
                print(f"  ok  {nome:26} {rota}")
            except Exception as exc:  # noqa: BLE001 - uma rota má não trava o resto
                falhados.append(f"{nome} ({rota}): {type(exc).__name__}")
                print(f"  ERRO {nome:26} {rota} :: {type(exc).__name__}: {str(exc)[:140]}")

        print("\nerros de consola (últimos):", len(erros))
        for linha in erros[-4:]:
            print("   ", linha[:160])
        contexto.close()

        # Landing page: contexto limpo e **sem** token (página pública).
        rota, nome, espera = ECRA_LANDING
        try:
            limpo = browser.new_context(viewport={"width": args.largura, "height": args.altura}, locale="pt-PT")
            pagina_limpa = limpo.new_page()
            pagina_limpa.goto(f"{args.base}{rota}", wait_until="load", timeout=60000)
            pagina_limpa.wait_for_timeout(int(espera * 1000))
            try:
                aceitar_cookies(pagina_limpa)
            except Exception:  # noqa: BLE001
                pass
            esconder_consentimento(pagina_limpa)
            pagina_limpa.screenshot(path=str(DESTINO / f"{nome}.png"), full_page=False)
            feitos.append(f"{nome} <- {rota}")
            print(f"  ok  {nome:26} {rota} (sem sessão)")
            limpo.close()
        except Exception as exc:  # noqa: BLE001
            falhados.append(f"{nome} ({rota}): {type(exc).__name__}")
            print(f"  ERRO {nome:26} {rota} :: {type(exc).__name__}: {str(exc)[:140]}")

        browser.close()

    (DESTINO / "_indice.json").write_text(
        json.dumps({"ecras": feitos, "falhados": falhados}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n{len(feitos)} ecrã(s) em {DESTINO}")
    return 0 if feitos else 1


if __name__ == "__main__":
    sys.exit(main())
