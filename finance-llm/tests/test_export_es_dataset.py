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
    assert "62 568,00 €" in completion
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


def test_entidade_precisa_de_nome_ou_nif() -> None:
    documento = {"name": "Município de Chaves", "nif": "501205551", "country": "Portugal", "contracts_count": 12,
                 "as_adjudicante_count": 12, "as_adjudicatario_count": 0, "total_value": 1000.5}
    prompt, completion, _ = exporter._build_entidade(documento, exporter.DEFAULT_MAX_CHARS)

    assert "Contratos registados: 12" in prompt
    assert "Município de Chaves (NIF 501205551, Portugal)" in completion
    assert exporter._build_entidade({}, exporter.DEFAULT_MAX_CHARS) is None


def test_todas_as_receitas_apontam_para_um_indice() -> None:
    assert sorted(exporter.RECIPES) == ["contratos", "contratos-es", "contratos-fr", "empresas", "noticias"]
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
