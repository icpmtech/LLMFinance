"""Publica a loja do «Sabemos» numa instalação em uso.

O deploy de código **não** envia a pasta `data/`, por isso uma instalação que
já exista (produção incluída) não recebe nem o rebranding da loja nem as imagens
de produto que vêm com o código. Isto aplica as duas coisas pela API do próprio
`shop_store`/`cms_store`, para as alterações ficarem com atividade registada,
como se tivessem sido feitas na gestão da loja.

    python _atualizar_loja_sabemos.py

Pode ser corrido mais de uma vez: o nome só é trocado enquanto estiver no valor
antigo (não desfaz uma escolha feita na loja), as imagens não duplicam e os
produtos que já tenham imagem não são tocados.
"""
from __future__ import annotations

from api import shop_store as store

AUTOR = "migracao@sabemos.studio"

#: Como a loja se chamava antes: só estes valores são substituídos.
NOMES_ANTIGOS = ("", "Loja IQ OS")
RODAPE_ANTIGO = ("", "© Loja IQ OS — todos os direitos reservados.")


def _rebranding() -> None:
    """Passa o nome e o rodapé da loja para a marca «Sabemos»."""
    settings = store.get_settings()
    mudancas = {}
    if str(settings.get("store_name") or "").strip() in NOMES_ANTIGOS:
        mudancas["store_name"] = store.DEFAULT_SETTINGS["store_name"]
    if str(settings.get("footer_text") or "").strip() in RODAPE_ANTIGO:
        mudancas["footer_text"] = store.DEFAULT_SETTINGS["footer_text"]
    if str(settings.get("description") or "").strip() in ("", "Loja da plataforma: relatórios, dossiês, dados e formação para decisões informadas."):
        mudancas["description"] = store.DEFAULT_SETTINGS["description"]
    if not mudancas:
        print("  marca: já estava atualizada")
        return
    store.save_settings(mudancas, AUTOR)
    for campo, valor in mudancas.items():
        print(f"  marca: {campo} = {valor}")


def _imagens() -> None:
    """Liga a cada produto a imagem de marca que viaja com o código."""
    resultado = store.instalar_imagens_de_produto(AUTOR)
    if not resultado["instalados"]:
        print("  imagens: já estavam todas ligadas")
        return
    print(f"  imagens: ligadas a {resultado['instalados']} produto(s)")


def main() -> None:
    _rebranding()
    _imagens()
    settings = store.get_settings()
    print(f"loja: {settings['store_name']} · {settings['footer_text']}")


if __name__ == "__main__":
    main()
