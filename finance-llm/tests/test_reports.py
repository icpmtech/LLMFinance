"""Relatórios a pedido: catálogo, pedidos, pagamento MB Way e backoffice.

O que se testa aqui é o **domínio** (não as rotas HTTP): é ele que decide se um
pedido pode avançar sem pagamento, quem é avisado, que ficheiros ficam
disponíveis e o que o cliente pode ver. O bug que isto previne é o clássico
«pedido grátis ficou a aguardar pagamento para sempre» ou «cliente vê notas
internas do backoffice».
"""
from __future__ import annotations

import base64

import pytest

from api import reports_payments as payments
from api import reports_store as store


@pytest.fixture()
def loja(tmp_path, monkeypatch):
    """Documento de relatórios isolado em `tmp_path` (sem tocar em `data/`)."""
    monkeypatch.setattr(store, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(store, "REPORTS_PATH", tmp_path / "reports" / "reports.json")
    monkeypatch.setattr(store, "FILES_DIR", tmp_path / "reports" / "files")
    store.reset_for_tests()
    yield store
    store.reset_for_tests()


def _pedido(package_id: str = "financeiro-resumido", **extra):
    payload = {"package_id": package_id, "targets": [{"name": "CILAG, LDA", "nif": "500697370"}], "notes": "Urgente, sff."}
    payload.update(extra)
    return store.create_request({"email": "cliente@exemplo.pt", "name": "Cliente Exemplo"}, payload)


# ------------------------------------------------------------------ catálogo
def test_catalogo_por_omissao(loja):
    """Os quatro pacotes anunciados e o número MB Way configurado de origem."""
    ids = [item["id"] for item in store.catalogue(only_active=True)]
    assert ids == ["corporativo", "financeiro-resumido", "financeiro-detalhado", "concorrencia"]
    precos = {item["id"]: item["price"] for item in store.catalogue()}
    assert precos == {"corporativo": 0.0, "financeiro-resumido": 18.0, "financeiro-detalhado": 24.0, "concorrencia": 130.0}
    assert store.settings()["mbway_number"] == "919520386"
    # A chave de API nunca sai na vista pública.
    assert "mbway_api_key" not in store.public_settings()
    assert store.public_settings()["mbway_number"] == "919520386"


def test_numero_mbway_normalizado_e_validado(loja):
    assert store.save_settings({"mbway_number": "+351 919 520 386"})["mbway_number"] == "919520386"
    assert store.save_settings({"mbway_number": "00351 919520386"})["mbway_number"] == "919520386"
    with pytest.raises(ValueError):
        store.save_settings({"mbway_number": "12345"})
    # Um número inválido não deve ter ficado gravado.
    assert store.settings()["mbway_number"] == "919520386"


def test_backoffice_por_lista_de_emails(loja):
    store.save_settings({"backoffice_users": ["Ana@Exemplo.pt", "ana@exemplo.pt", "invalido"]})
    assert store.backoffice_users() == ["ana@exemplo.pt"]
    assert store.is_backoffice("ana@exemplo.pt") is True
    assert store.is_backoffice("ANA@EXEMPLO.PT") is True
    assert store.is_backoffice("outro@exemplo.pt") is False
    # Administradores entram sempre, mesmo sem estarem na lista.
    assert store.is_backoffice("admin@exemplo.pt", "admin") is True


# --------------------------------------------------------------------- totais
def test_totais_com_iva_incluido(loja):
    """O preço do catálogo é o preço final (IVA incluído à taxa configurada)."""
    valores = store.totals(24, 23)
    assert valores["total"] == 24.0
    assert round(valores["subtotal"] + valores["vat"], 2) == 24.0
    assert valores["vat"] == pytest.approx(4.49, abs=0.01)


# -------------------------------------------------------------------- pedidos
def test_pedido_pago_comeca_a_aguardar_pagamento(loja):
    pedido = _pedido()
    assert pedido["status"] == "aguarda_pagamento"
    assert pedido["reference"].startswith("REL-")
    assert pedido["amounts"]["total"] == 18.0
    assert pedido["payment"]["status"] == "pendente"
    assert pedido["payment"]["mbway_number"] == "919520386"
    # O cliente tem de saber onde transferir e com que referência.
    assert pedido["payment"]["mbway_reference"] == pedido["reference"].rsplit("-", 1)[-1]
    assert pedido["targets_label"] == "CILAG, LDA (500697370)"
    assert [item["id"] for item in pedido["flow"]][:2] == ["aguarda_pagamento", "pagamento_confirmado"]
    assert pedido["next_statuses"][0]["id"] == "pagamento_confirmado"


def test_pedido_gratis_entra_direto_em_producao(loja):
    pedido = _pedido("corporativo")
    assert pedido["amounts"]["total"] == 0.0
    assert pedido["status"] == "em_producao"
    assert pedido["payment"]["status"] == "confirmado"
    assert pedido["payment"]["confirmed_by"].startswith("sistema")


def test_numero_de_referencias_por_ano(loja):
    primeiro = _pedido("corporativo")
    segundo = _pedido("corporativo")
    assert primeiro["reference"].endswith("0001")
    assert segundo["reference"].endswith("0002")


def test_limite_de_alvos_do_pacote(loja):
    cinco = [{"name": f"Empresa {i}", "nif": f"50000000{i}"} for i in range(5)]
    assert store.create_request({"email": "c@exemplo.pt"}, {"package_id": "concorrencia", "targets": cinco})["targets"]
    seis = [{"name": f"Empresa {i}", "nif": f"50000000{i}"} for i in range(6)]
    assert len(store.create_request({"email": "c@exemplo.pt"}, {"package_id": "concorrencia", "targets": seis})["targets"]) == 6
    sete = [{"name": f"Empresa {i}"} for i in range(7)]
    with pytest.raises(ValueError):
        store.create_request({"email": "c@exemplo.pt"}, {"package_id": "concorrencia", "targets": sete})
    with pytest.raises(ValueError):
        store.create_request({"email": "c@exemplo.pt"}, {"package_id": "financeiro-resumido", "targets": [{"name": "A"}, {"name": "B"}]})


def test_pedido_sem_alvo_e_recusado(loja):
    with pytest.raises(ValueError):
        store.create_request({"email": "c@exemplo.pt"}, {"package_id": "corporativo", "targets": []})


def test_pacote_inexistente_ou_desativado(loja):
    with pytest.raises(ValueError):
        store.create_request({"email": "c@exemplo.pt"}, {"package_id": "nao-existe", "targets": [{"name": "A"}]})
    store.save_package({"id": "corporativo", "active": False})
    with pytest.raises(ValueError):
        store.create_request({"email": "c@exemplo.pt"}, {"package_id": "corporativo", "targets": [{"name": "A"}]})


def test_apenas_os_pedidos_do_proprio(loja):
    meu = store.create_request({"email": "eu@exemplo.pt", "name": "Eu"}, {"package_id": "corporativo", "targets": [{"name": "A"}]})
    store.create_request({"email": "outro@exemplo.pt", "name": "Outro"}, {"package_id": "corporativo", "targets": [{"name": "B"}]})
    minha_lista = store.requests_for("eu@exemplo.pt")
    assert [item["id"] for item in minha_lista] == [meu["id"]]


# ------------------------------------------------------------------ pagamento
def test_fluxo_de_pagamento_notifica_os_dois_lados(loja):
    store.save_settings({"backoffice_users": ["back@exemplo.pt"]})
    pedido = _pedido()
    assert store.unread_count("back@exemplo.pt") >= 1  # aviso de pedido novo

    store.declare_payment(pedido["id"], {"email": "cliente@exemplo.pt", "name": "Cliente"}, {"method": "mbway", "mbway_phone": "912345678"})
    declarado = store.get_request_view(pedido["id"], include_internal=True)
    assert declarado["payment"]["status"] == "aguarda_confirmacao"
    assert declarado["payment"]["mbway_phone"] == "912345678"
    # O estado do pedido ainda não mudou: quem confirma é o backoffice.
    assert declarado["status"] == "aguarda_pagamento"
    assert store.unread_count("back@exemplo.pt") >= 2

    confirmado = store.set_payment_result(pedido["id"], "back@exemplo.pt", "confirm", note="MB Way 912345678")
    assert confirmado["payment"]["status"] == "confirmado"
    assert confirmado["status"] == "pagamento_confirmado"
    assert confirmado["payment"]["confirmed_by"] == "back@exemplo.pt"
    # O cliente é avisado.
    assert store.unread_count("cliente@exemplo.pt") >= 1


def test_pagamento_rejeitado_avisa_o_cliente(loja):
    pedido = _pedido()
    store.declare_payment(pedido["id"], {"email": "cliente@exemplo.pt"}, {"method": "mbway", "mbway_phone": "912345678"})
    rejeitado = store.set_payment_result(pedido["id"], "back@exemplo.pt", "reject", note="Não encontrámos o pagamento.")
    assert rejeitado["payment"]["status"] == "rejeitado"
    assert rejeitado["status"] == "aguarda_pagamento"
    assert any("Não encontrámos" in item["body"] for item in store.notifications_for("cliente@exemplo.pt"))


def test_pagamento_automatico_confirma_sem_humano(loja):
    pedido = _pedido()
    store.declare_payment(pedido["id"], {"email": "cliente@exemplo.pt"}, {"method": "mbway", "mbway_phone": "912345678"})
    assert store.register_automatic_payment(pedido["id"], reference=pedido["reference"]) is not None
    atual = store.get_request_view(pedido["id"], include_internal=True)
    assert atual["payment"]["status"] == "confirmado"
    assert atual["payment"]["automatic"] is True
    assert atual["status"] == "pagamento_confirmado"


def test_pagamento_de_outro_utilizador_e_recusado(loja):
    pedido = _pedido()
    with pytest.raises(ValueError):
        store.declare_payment(pedido["id"], {"email": "intruso@exemplo.pt"}, {"method": "mbway"})
    with pytest.raises(ValueError):
        store.cancel(pedido["id"], {"email": "intruso@exemplo.pt"})


def test_pagamento_duplicado_e_recusado(loja):
    pedido = _pedido()
    store.set_payment_result(pedido["id"], "back@exemplo.pt", "confirm")
    with pytest.raises(ValueError):
        store.declare_payment(pedido["id"], {"email": "cliente@exemplo.pt"}, {"method": "mbway"})


# ---------------------------------------------------------------------- fluxo
def test_fluxo_ate_gerado_com_ficheiro(loja):
    pedido = _pedido()
    store.set_payment_result(pedido["id"], "back@exemplo.pt", "confirm")
    store.set_status(pedido["id"], "back@exemplo.pt", "em_producao")
    vista = store.add_file(pedido["id"], "back@exemplo.pt", name="relatorio cilag.pdf", data=b"%PDF-1.4 teste", mime="application/pdf")
    assert vista["status"] == "gerado"
    assert vista["files"][0]["name"] == "relatorio_cilag.pdf"
    encontrado = store.file_of(pedido["id"], vista["files"][0]["id"])
    assert encontrado is not None
    assert encontrado[0].read_bytes().startswith(b"%PDF")
    # O cliente é avisado de que está pronto.
    assert any(item["kind"] == "gerado" for item in store.notifications_for("cliente@exemplo.pt"))
    # E a entrega fecha o ciclo.
    entregue = store.set_status(pedido["id"], "cliente@exemplo.pt", "entregue")
    assert entregue["status"] == "entregue"


def test_ficheiro_por_base64(loja):
    pedido = _pedido()
    dados = base64.b64encode(b"conteudo").decode()
    vista = store.add_file_base64(pedido["id"], "back@exemplo.pt", {"name": "nota.txt", "data": dados, "mime": "text/plain"})
    assert vista["files"][0]["size"] == len(b"conteudo")


def test_extensao_e_tamanho_de_ficheiro(loja):
    pedido = _pedido()
    with pytest.raises(ValueError):
        store.add_file(pedido["id"], "back@exemplo.pt", name="virus.exe", data=b"MZ")
    with pytest.raises(ValueError):
        store.add_file(pedido["id"], "back@exemplo.pt", name="vazio.pdf", data=b"")


def test_cancelar_so_antes_de_produzir(loja):
    pedido = _pedido()
    cancelado = store.cancel(pedido["id"], {"email": "cliente@exemplo.pt"}, "Já não preciso.")
    assert cancelado["status"] == "cancelado"
    # Um pedido cancelado não volta atrás nem aceita pagamentos.
    with pytest.raises(ValueError):
        store.set_status(pedido["id"], "back@exemplo.pt", "em_producao")
    with pytest.raises(ValueError):
        store.declare_payment(pedido["id"], {"email": "cliente@exemplo.pt"}, {"method": "mbway"})


def test_cancelar_em_producao_e_recusado(loja):
    pedido = _pedido()
    store.set_payment_result(pedido["id"], "back@exemplo.pt", "confirm")
    store.set_status(pedido["id"], "back@exemplo.pt", "em_producao")
    with pytest.raises(ValueError):
        store.cancel(pedido["id"], {"email": "cliente@exemplo.pt"})


# --------------------------------------------------------- notas e visibilidade
def test_nota_interna_nao_sai_para_o_cliente(loja):
    pedido = _pedido()
    store.attach_note(pedido["id"], "back@exemplo.pt", "Cliente é devedor; ter cuidado.", internal=True)
    store.attach_note(pedido["id"], "back@exemplo.pt", "Pedido recebido.")
    do_cliente = store.get_request_view(pedido["id"])
    mensagens = [item["message"] for item in do_cliente["history"]]
    assert "Pedido recebido." in mensagens
    assert "Cliente é devedor; ter cuidado." not in mensagens
    assert do_cliente["internal_note"] == ""
    do_backoffice = store.get_request_view(pedido["id"], include_internal=True)
    assert any("devedor" in item["message"] for item in do_backoffice["history"])
    assert "devedor" in do_backoffice["internal_note"]


def test_estado_invalido_e_recusado(loja):
    pedido = _pedido()
    with pytest.raises(ValueError):
        store.set_status(pedido["id"], "back@exemplo.pt", "inventado")


# ------------------------------------------------------------------ indicadores
def test_indicadores_e_exportacao(loja):
    pago = _pedido()
    store.set_payment_result(pago["id"], "back@exemplo.pt", "confirm")
    store.create_request({"email": "cliente@exemplo.pt"}, {"package_id": "corporativo", "targets": [{"name": "Grátis"}]})
    indicadores = store.stats()
    assert indicadores["total"] == 2
    assert indicadores["by_status"]["pagamento_confirmado"] == 1
    assert indicadores["by_status"]["em_producao"] == 1
    assert indicadores["revenue"] == 18.0
    linhas = store.csv_rows()
    assert linhas[0][0] == "Referência"
    assert len(linhas) == 3
    assert any("18,00" in linha[4] for linha in linhas[1:])


# --------------------------------------------------------------- MB Way (API)
def test_mbway_sem_chave_nao_chama_a_rede(loja):
    assert payments.api_configured(store.settings()) is False
    resultado = payments.create_payment_request(store.settings(), phone="912345678", amount=18, reference="REL-1")
    assert resultado["ok"] is False
    assert resultado["configured"] is False


def test_mbway_formato_do_telefone():
    assert payments.normalise_phone_351("912345678") == "351#912345678"
    assert payments.normalise_phone_351("+351 912 345 678") == "351#912345678"
    assert payments.normalise_phone_351("") == ""
    assert store.normalise_phone("919520386") == "919520386"
    assert store.normalise_phone("219520386") == ""  # fixo, não é telemóvel
