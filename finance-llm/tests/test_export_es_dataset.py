"""Testes do exporter de datasets do Elasticsearch para o Soup.

Correr com:

    c:\\LLMFinance\\.venv\\Scripts\\python.exe -m pytest tests/test_export_es_dataset.py -q

Cobrem o que é fácil de partir sem se dar por isso:

1. a normalização dos campos (adjudicantes ``raw``/``parsed``, ``titulaires``
   franceses sem nome, CPV com ``description``/``nom``, valores em euros);
2. a recusa de documentos sem o mínimo para formar um par;
3. a escrita do JSONL — formato Alpaca, sem ficheiros truncados.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from training import export_es_dataset as exporter


# ---------------------------------------------------------------- normalização
def test_nomes_preferem_parsed_a_raw() -> None:
    """``parsed`` traz o nome limpo; ``raw`` só é usado quando ele falta."""
    campo = {"raw": ["501205551 - Município de Chaves"], "parsed": [{"nif": "501205551", "nome": "Município de Chaves"}]}
    assert exporter._names(campo) == ["Município de Chaves"]


def test_nomes_caem_para_raw_quando_parsed_vem_vazio() -> None:
    campo = {"raw": ["A - Empresa A", "B - Empresa B"], "parsed": []}
    assert exporter._names(campo) == ["A - Empresa A", "B - Empresa B"]


def test_titulares_franceses_sem_nome_usam_o_identificador() -> None:
    """Nos contratos franceses o ``nom`` vem vazio; o SIRET é o que resta."""
    titulaires = [
        {"type_identifiant": "SIRET", "id": "34348850800924", "nom": ""},
        {"type_identifiant": "SIRET", "id": "48523483500018", "nom": "Empresa B"},
    ]
    assert exporter._names(titulaires) == ["SIRET 34348850800924", "Empresa B"]


def test_cpv_aceita_description_espanhola_e_nome_frances() -> None:
    assert exporter._cpv_label([{"code": "55300000-3", "description": "Serviços de mesa"}]) == "Serviços de mesa"
    assert exporter._cpv_label([{"code": "90500000-2", "nom": "Services d'assainissement"}], "fr") == "Services d'assainissement"
    assert exporter._cpv_label([{"code": "55300000-3"}]) == "55300000-3"
    assert exporter._cpv_label([]) == "não especificado"
    assert exporter._cpv_label([], "fr") == "non précisé"


def test_money_formata_em_portugues() -> None:
    assert exporter._money(62568.0) == "62 568,00 €"
    assert exporter._money(None) == "não especificado"
    assert exporter._money("") == "não especificado"


def test_clean_colapsa_espacos() -> None:
    assert exporter._clean("Serviços de\n  mesa\te restauração ") == "Serviços de mesa e restauração"


def test_clean_desfaz_entidades_html() -> None:
    """Os nomes vêm com ``&amp;`` do Elasticsearch e isso ia direto para o treino."""
    assert exporter._clean("OLIVEIRA &amp; PIRES") == "OLIVEIRA & PIRES"
    assert exporter._clean("Construções &quot;Dois Irmãos&quot;") == 'Construções "Dois Irmãos"'


# ------------------------------------------------------------------ contratos PT
DOC_PT = {
    "idcontrato": "11970012",
    "objectoContrato": "Aquisição de serviços de cedência de espaço",
    "descContrato": "Almoço Convívio de Natal Sénior",
    "adjudicantes": {"raw": ["501205551 - Município de Chaves"], "parsed": [{"nif": "501205551", "nome": "Município de Chaves"}]},
    "adjudicatarios": {"raw": ["509136826 - Quinta do Príncipe"], "parsed": [{"nif": "509136826", "nome": "Quinta do Príncipe"}]},
    "tipoContrato": ["Aquisição de serviços"],
    "tipoprocedimento": "Consulta Prévia",
    "precoContratual": 62568.0,
    "cpv": [{"code": "55300000-3", "description": "Serviços de mesa e de restauração"}],
    "dataPublicacao": "2025-11-21",
    "regime": "Código dos Contratos Públicos",
    "Ano": 2025,
}


def test_contrato_pt_gera_o_par_completo() -> None:
    prompt, completion, metadata = exporter._build_contrato_pt(DOC_PT, exporter.DEFAULT_MAX_CHARS)

    assert "Contrato 11970012 - Aquisição de serviços" in prompt
    assert "Adjudicante: Município de Chaves" in prompt
    assert "Adjudicatário: Quinta do Príncipe" in prompt
    assert "Preço contratual: 62568.0" in prompt
    assert "62568.0 €" in completion
    assert "Serviços de mesa e de restauração" in completion
    assert metadata == {"idcontrato": "11970012", "ano": 2025, "tipoContrato": ["Aquisição de serviços"]}


def test_contrato_pt_sem_identificador_e_descartado() -> None:
    """Sem identificador o par não ensina nada — o exporter salta-o."""
    assert exporter._build_contrato_pt({**DOC_PT, "idcontrato": ""}, exporter.DEFAULT_MAX_CHARS) is None


def test_contrato_pt_usa_a_descricao_quando_falta_o_objecto() -> None:
    prompt, _, _ = exporter._build_contrato_pt({**DOC_PT, "objectoContrato": ""}, exporter.DEFAULT_MAX_CHARS)
    assert "Almoço Convívio de Natal Sénior" in prompt


def test_contrato_pt_sem_objecto_nem_descricao_e_descartado() -> None:
    documento = {**DOC_PT, "objectoContrato": "", "descContrato": ""}
    assert exporter._build_contrato_pt(documento, exporter.DEFAULT_MAX_CHARS) is None


def test_max_chars_corta_o_prompt_e_a_descricao() -> None:
    documento = {**DOC_PT, "objectoContrato": "x" * 500}
    prompt, _, _ = exporter._build_contrato_pt(documento, 100)

    assert len(prompt) < 300
    assert prompt.endswith("…")


def test_contrato_pt_pede_todos_os_campos_que_a_resposta_cita() -> None:
    """Data, regime e CPV apareciam na resposta mas não no pedido.

    Isso ensinou o modelo a inventá-los: com um documento sem data, respondia
    «publicado a 2021-08-26» e «regime DL 18/2008». O teste fixa a regra: cada
    valor citado no *output* tem de existir no *input*.
    """
    prompt, completion, _ = exporter._build_contrato_pt(DOC_PT, exporter.DEFAULT_MAX_CHARS)

    assert "Data de publicação: 2025-11-21" in prompt
    assert "Regime: Código dos Contratos Públicos" in prompt
    assert "CPV principal: Serviços de mesa e de restauração" in prompt
    assert "publicado a 2025-11-21" in completion
    assert "regime Código dos Contratos Públicos" in completion


def test_contrato_pt_sem_data_nao_inventa_data() -> None:
    """Sem ``dataPublicacao`` o campo sai do pedido **e** da resposta.

    Antes o pedido dizia «data desconhecida» e a resposta repetia o marcador;
    agora o modelo vê o par sem o campo, que é o que o ensina a calar-se quando
    o documento do chat não traz a data.
    """
    documento = {**DOC_PT, "dataPublicacao": None, "regime": ""}
    prompt, completion, _ = exporter._build_contrato_pt(documento, exporter.DEFAULT_MAX_CHARS)

    assert "Data de publicação" not in prompt
    assert "Regime:" not in prompt
    assert "publicado a" not in completion
    assert "data desconhecida" not in completion
    assert "Este contrato, liga" not in completion


def test_variantes_cobrem_as_tres_instrucoes_da_interface() -> None:
    """A página oferece descrever/auditar/cidadão; o treino só tinha descrever."""
    pares = exporter._build_contrato_pt_variantes(DOC_PT, exporter.DEFAULT_MAX_CHARS)

    assert pares is not None
    instrucoes = [instrucao for instrucao, *_ in pares]
    assert instrucoes == [
        "Descreve este contrato público português.",
        "Resume este contrato numa frase, para um cidadão.",
        "Audita este contrato e aponta o que deve ser verificado.",
    ]
    # O mesmo documento, três respostas diferentes — e todas ancoradas no pedido.
    assert len({completion for _, _, completion, _ in pares}) == 3
    for _, prompt, completion, _ in pares:
        assert prompt == pares[0][1]
        assert "Quinta do Príncipe" in completion
        assert "62568.0 €" in completion


def test_variantes_descartam_o_documento_sem_campos_suficientes() -> None:
    assert exporter._build_contrato_pt_variantes({**DOC_PT, "idcontrato": ""}, exporter.DEFAULT_MAX_CHARS) is None


def test_sinais_de_risco_so_apontam_o_que_o_documento_permite() -> None:
    """Acima do limite do ajuste direto é sinal; abaixo, só um lembrete."""
    alto = exporter._sinais_de_risco("Ajuste Direto Regime Geral", 120000.0, "Obra Lda")
    baixo = exporter._sinais_de_risco("Ajuste Direto Regime Geral", 15430.75, "Obra Lda")

    assert "acima do limite legal" in alto
    assert "acima do limite legal" not in baixo
    assert "adjudicatário único" in alto
    assert "adjudicatário único" not in exporter._sinais_de_risco("Concurso público", 1.0, "A, B")



# ------------------------------------------------------------------- outros índices
def test_contrato_fr_usa_o_siret_quando_nao_ha_nome() -> None:
    documento = {
        "id": "202343L01",
        "objet": "Collecte et evacuation des dechets dangereux",
        "acheteur_id": "25430075900027",
        "acheteur_nom": "",
        "titulaires": [{"type_identifiant": "SIRET", "id": "34348850800924", "nom": ""}],
        "montant": 1160968.62,
        "date_publication": "2003-06-16",
        "cpv": [{"code": "90500000-2", "nom": "Services d'assainissement"}],
    }
    prompt, completion, _ = exporter._build_contrato_fr(documento, exporter.DEFAULT_MAX_CHARS)

    assert "Comprador: entidade 25430075900027" in prompt
    assert "Titulares: SIRET 34348850800924" in prompt
    assert "Services d'assainissement" in completion


def test_noticia_exige_sentimento() -> None:
    documento = {"title": "Tech Stocks Decline", "sentiment": "negativo", "summary_pt": "O tom geral é negativo."}
    prompt, completion, metadata = exporter._build_noticia(documento, exporter.DEFAULT_MAX_CHARS)

    assert "Tech Stocks Decline" in prompt
    assert completion.startswith("Sentimento: negativo.")
    assert metadata["ticker"] == ""

    assert exporter._build_noticia({"title": "Sem sentimento"}, exporter.DEFAULT_MAX_CHARS) is None
    assert exporter._build_noticia({"sentiment": "positivo"}, exporter.DEFAULT_MAX_CHARS) is None


DOC_SUBVENCAO = {
    "entidade": "INSTITUTO DE GESTÃO FINANCEIRA DA SEGURANÇA SOCIAL, IP",
    "nif_entidade": "501205551",
    "beneficiario": "SOL DO AVE - ASSOCIAÇÃO PARA O DESENVOLVIMENTO INTEGRADO DO VALE DO AVE",
    "nif_beneficiario": "501234567",
    "beneficiario_tipo": "pessoa_coletiva",
    "montante": 238715.89,
    "finalidade": "Abordagens territoriais para a inclusão",
    "data_decisao": "2024-11-08",
    "ano": 2025,
    "tipo_ato": "Decreto-Lei",
    "numero_ato": "5",
    "fundamento_legal": "Decreto-Lei n.º 5",
}


def test_subvencao_gera_o_par_completo() -> None:
    prompt, completion, metadata = exporter._build_subvencao(DOC_SUBVENCAO, exporter.DEFAULT_MAX_CHARS)

    assert "Beneficiário: SOL DO AVE" in prompt
    assert "Entidade que atribui: INSTITUTO DE GESTÃO FINANCEIRA" in prompt
    assert "Montante: 238715.89" in prompt
    assert "Abordagens territoriais para a inclusão" in completion
    assert "238 715,89 €" in completion
    assert metadata["nif_beneficiario"] == "501234567"
    assert metadata["ano"] == 2025


@pytest.mark.parametrize("campo", ["beneficiario", "montante"])
def test_subvencao_sem_beneficiario_ou_montante_e_descartada(campo: str) -> None:
    """Sem quem recebeu nem quanto, o par não ensina nada."""
    assert exporter._build_subvencao({**DOC_SUBVENCAO, campo: None}, exporter.DEFAULT_MAX_CHARS) is None


def test_entidade_precisa_de_nome_ou_nif() -> None:
    documento = {"name": "Município de Chaves", "nif": "501205551", "country": "Portugal", "contracts_count": 12,
                 "as_adjudicante_count": 12, "as_adjudicatario_count": 0, "total_value": 1000.5}
    prompt, completion, _ = exporter._build_entidade(documento, exporter.DEFAULT_MAX_CHARS)

    assert "Contratos registados: 12" in prompt
    assert "Município de Chaves (NIF 501205551, Portugal)" in completion
    assert exporter._build_entidade({}, exporter.DEFAULT_MAX_CHARS) is None


def test_todas_as_receitas_apontam_para_um_indice() -> None:
    assert sorted(exporter.RECIPES) == [
        "contratos",
        "contratos-es",
        "contratos-fr",
        "empresas",
        "noticias",
        "subvencoes",
    ]
    for nome, receita in exporter.RECIPES.items():
        assert receita.index, nome
        assert receita.includes, nome
        assert receita.instruction, nome


# ------------------------------------------------------------------ índices à medida
def test_molde_deixa_o_marcador_intacto_quando_o_campo_falta() -> None:
    doc = {"title": "Notícia", "summary_pt": "Resumo"}
    assert exporter._flatten(doc) == {"title": "Notícia", "summary_pt": "Resumo"}

    build = exporter._make_custom_builder("{title}", "{summary_pt}")
    prompt, completion, _ = build(doc, exporter.DEFAULT_MAX_CHARS)
    assert (prompt, completion) == ("Notícia", "Resumo")

    build_em_falta = exporter._make_custom_builder("{nao_existe}", "{summary_pt}")
    assert build_em_falta(doc, exporter.DEFAULT_MAX_CHARS)[0] == "{nao_existe}"


def test_flatten_junta_listas_e_objetos() -> None:
    doc = {"topics": ["regulação", "preço"], "adjudicantes": {"parsed": [{"nome": "Chaves"}]}}
    assert exporter._flatten(doc) == {"topics": "regulação, preço", "adjudicantes": "Chaves"}


# ---------------------------------------------------------------------- escrita
class _FakeIndices:
    def exists(self, index: str) -> bool:
        return True


class _FakeClient:
    indices = _FakeIndices()

    def count(self, index: str, query: dict) -> dict:
        return {"count": 2}

    def close(self) -> None:
        pass


def test_export_escreve_alpaca_e_mete_o_indice_nos_metadados(tmp_path, monkeypatch) -> None:
    """O destino só é substituído no fim, e cada linha tem os quatro campos."""
    import elasticsearch.helpers as helpers

    documento = {"idcontrato": "1", "objectoContrato": "Um contrato", "adjudicantes": {"raw": []}, "adjudicatarios": {"raw": []}}

    monkeypatch.setattr(exporter, "_resolve_client", lambda es_url, timeout: _FakeClient())
    monkeypatch.setattr(helpers, "scan", lambda *a, **kw: [{"_source": documento}, {"_source": {}}])

    destino = tmp_path / "contratos.jsonl"
    stats = exporter.export(
        index="contratos",
        instruction="Descreve este contrato público português.",
        includes=("idcontrato",),
        builder=exporter._build_contrato_pt,
        out_path=destino,
    )

    assert stats == {"index": "contratos", "matched": 2, "read": 2, "written": 1, "skipped": 1, "dropped": 0}
    rows = [json.loads(linha) for linha in destino.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert set(rows[0]) == {"instruction", "input", "output", "metadata"}
    assert rows[0]["instruction"] == "Descreve este contrato público português."
    assert rows[0]["metadata"]["index"] == "contratos"
    # Não fica lixo atrás (o `.tmp` é renomeado para o destino).
    assert list(tmp_path.iterdir()) == [destino]


def test_export_nao_deixa_ficheiro_a_meio_quando_falha(tmp_path, monkeypatch) -> None:
    import elasticsearch.helpers as helpers

    def _rebenta(*args, **kwargs):
        yield {"_source": DOC_PT}
        raise RuntimeError("a ligação ao Elasticsearch caiu")

    monkeypatch.setattr(exporter, "_resolve_client", lambda es_url, timeout: _FakeClient())
    monkeypatch.setattr(helpers, "scan", _rebenta)

    destino = tmp_path / "contratos.jsonl"
    with pytest.raises(RuntimeError):
        exporter.export(
            index="contratos",
            instruction="Descreve este contrato público português.",
            includes=("idcontrato",),
            builder=exporter._build_contrato_pt,
            out_path=destino,
        )

    assert not destino.exists()
    assert list(tmp_path.iterdir()) == []


def test_orcamento_de_tokens_deixa_de_fora_os_pares_compridos(tmp_path, monkeypatch) -> None:
    """O `soup train` aborta a corrida inteira se uma linha não couber: mais vale
    não a escrever."""
    import elasticsearch.helpers as helpers

    documentos = [
        {"idcontrato": "1", "objectoContrato": "curto"},
        {"idcontrato": "2", "objectoContrato": "x" * 400},
    ]

    monkeypatch.setattr(exporter, "_resolve_client", lambda es_url, timeout: _FakeClient())
    monkeypatch.setattr(helpers, "scan", lambda *a, **kw: [{"_source": d} for d in documentos])

    # Limite logo acima do par curto: o comprido tem de ficar de fora.
    curto = exporter._build_contrato_pt(documentos[0], exporter.DEFAULT_MAX_CHARS)
    limite = len(curto[0]) + len(curto[1]) + 10

    destino = tmp_path / "contratos.jsonl"
    stats = exporter.export(
        index="contratos",
        instruction="Descreve este contrato público português.",
        includes=("idcontrato",),
        builder=exporter._build_contrato_pt,
        out_path=destino,
        count_tokens=len,
        max_tokens=limite,
    )

    assert stats["written"] == 1
    assert stats["dropped"] == 1
    linhas = destino.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 1
    assert json.loads(linhas[0])["input"].startswith("Contrato 1 ")


def test_seed_pede_amostra_aleatoria_ao_elasticsearch(tmp_path, monkeypatch) -> None:
    """Sem `preserve_order` o `scan` repõe `sort: _doc` e a semente não faz nada."""
    import elasticsearch.helpers as helpers

    capturado = {}

    def _scan(client, **kwargs):
        capturado.update(kwargs)
        return []

    monkeypatch.setattr(exporter, "_resolve_client", lambda es_url, timeout: _FakeClient())
    monkeypatch.setattr(helpers, "scan", _scan)

    exporter.export(
        index="finance_subvencoes",
        instruction="Descreve este subsídio público português.",
        includes=("beneficiario",),
        builder=exporter._build_subvencao,
        out_path=tmp_path / "subvencoes.jsonl",
        seed=42,
    )

    assert capturado["preserve_order"] is True
    assert capturado["query"]["query"]["function_score"]["random_score"] == {"seed": 42, "field": "_seq_no"}

    capturado.clear()
    exporter.export(
        index="finance_subvencoes",
        instruction="Descreve este subsídio público português.",
        includes=("beneficiario",),
        builder=exporter._build_subvencao,
        out_path=tmp_path / "subvencoes.jsonl",
    )

    assert capturado["preserve_order"] is False
    assert "function_score" not in capturado["query"]["query"]


def test_dry_run_nao_escreve_nada(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(exporter, "_resolve_client", lambda es_url, timeout: _FakeClient())
    destino = tmp_path / "contratos.jsonl"

    stats = exporter.export(
        index="contratos",
        instruction="Descreve este contrato público português.",
        includes=("idcontrato",),
        builder=exporter._build_contrato_pt,
        out_path=destino,
        dry_run=True,
    )

    assert stats["dry_run"] is True
    assert stats["matched"] == 2
    assert not destino.exists()


# --------------------------------------------------------------- várias fontes
def test_export_many_junta_fontes_num_so_ficheiro(tmp_path, monkeypatch) -> None:
    """Um dataset pode misturar índices — é o que permite treinar um só modelo
    sobre contratos e empresas, cada linha com a sua instrução."""
    import elasticsearch.helpers as helpers

    por_indice = {
        "contratos": [{"idcontrato": "1", "objectoContrato": "Um contrato"}],
        "finance_entities": [{"name": "Município de Chaves", "nif": "501205551"}],
    }

    monkeypatch.setattr(exporter, "_resolve_client", lambda es_url, timeout: _FakeClient())
    monkeypatch.setattr(helpers, "scan", lambda client, index, **kw: [{"_source": d} for d in por_indice[index]])

    destino = tmp_path / "iqos.jsonl"
    stats = exporter.export_many(
        sources=[
            exporter.Source(index="contratos", instruction="Descreve este contrato.",
                            includes=(), builder=exporter._build_contrato_pt, label="contratos"),
            exporter.Source(index="finance_entities", instruction="Descreve esta entidade.",
                            includes=(), builder=exporter._build_entidade, label="empresas"),
        ],
        out_path=destino,
    )

    assert stats["index"] == "contratos+finance_entities"
    assert stats["read"] == 2
    assert stats["written"] == 2
    assert [(fonte["label"], fonte["written"]) for fonte in stats["fontes"]] == [("contratos", 1), ("empresas", 1)]

    linhas = [json.loads(linha) for linha in destino.read_text(encoding="utf-8").splitlines()]
    assert [linha["metadata"]["fonte"] for linha in linhas] == ["contratos", "empresas"]
    assert [linha["instruction"] for linha in linhas] == ["Descreve este contrato.", "Descreve esta entidade."]


def test_export_many_exige_fontes() -> None:
    with pytest.raises(ValueError):
        exporter.export_many(sources=[], out_path=Path("nao.jsonl"))


def test_cli_aceita_varios_datasets_e_recusa_query_com_mais_que_um(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(exporter, "_resolve_client", lambda es_url, timeout: _FakeClient())

    codigo = exporter.main([
        "--dataset", "contratos", "--dataset", "empresas",
        "--out", str(tmp_path / "iqos.jsonl"), "--dry-run",
    ])

    assert codigo == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["index"] == "contratos+finance_entities"
    assert stats["dry_run"] is True

    with pytest.raises(SystemExit):
        exporter.main(["--dataset", "contratos", "--dataset", "empresas", "--query", '{"match_all": {}}'])

# ------------------------------------------------- dropout de campos opcionais
def _doc_contrato() -> dict:
    return {
        "idcontrato": "772453",
        "objectoContrato": "limpeza de coletores",
        "adjudicantes": [{"nome": "Municipio de Condeixa-a-Nova"}],
        "adjudicatarios": [{"nome": "OLIVEIRA & PIRES"}],
        "tipoContrato": ["Aquisicao de servicos"],
        "tipoprocedimento": "Ajuste Direto Regime Geral",
        "precoContratual": "20806.2",
        "dataPublicacao": "2013-06-05",
        "regime": "DL 18/2008",
        "cpv": "90470000",
    }


def test_sem_dropout_a_resposta_cita_data_e_regime() -> None:
    exporter.definir_dropout(0)
    prompt, completion, _ = exporter._build_contrato_pt(_doc_contrato(), 0)
    assert "Data de publicacao: 2013-06-05" in prompt.replace("ç", "c").replace("ã", "a")
    assert "publicado a 2013-06-05" in completion


def test_dropout_remove_o_campo_do_pedido_e_da_resposta() -> None:
    """O modelo aprende a nao citar o que o documento nao traz."""
    exporter.definir_dropout(1.0, seed=42)
    try:
        prompt, completion, _ = exporter._build_contrato_pt(_doc_contrato(), 0)
    finally:
        exporter.definir_dropout(0)
    for campo in ("Data de publica", "Regime:", "CPV principal", "Tipo:", "Procedimento:"):
        assert campo not in prompt, f"{campo} devia ter saido do pedido"
    assert "publicado a" not in completion
    assert "regime" not in completion
    assert "Este contrato liga" in completion
    # O essencial fica sempre.
    assert "20806.2" in prompt and "20806.2" in completion


def test_dropout_e_reprodutivel() -> None:
    exporter.definir_dropout(0.5, seed=7)
    try:
        primeiro = exporter._build_contrato_pt(_doc_contrato(), 0)
        segundo = exporter._build_contrato_pt(_doc_contrato(), 0)
    finally:
        exporter.definir_dropout(0)
    assert primeiro == segundo
