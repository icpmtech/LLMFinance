"""Testes do registo de regras (`api/padroes_regras.py`) — puros, sem rede.

Cobrem o que é fácil partir: a validação (campo/operador/valor), a comparação
com outro campo (regras relativas), a persistência atómica, o CRUD, os templates
e a reposição das predefinições.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import padroes_regras as regras  # noqa: E402


@pytest.fixture(autouse=True)
def _estado_isolado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Cada teste corre sobre um ficheiro próprio (nunca toca nos dados reais)."""
    monkeypatch.setattr(regras, "PATH", tmp_path / "regras.json")
    regras.reset_state_cache()
    yield
    regras.reset_state_cache()


# ---------------------------------------------------------------------------
# Catálogo e predefinições
# ---------------------------------------------------------------------------
def test_predefinicoes_sao_materializadas_no_primeiro_arranque() -> None:
    estado = regras.listar()
    assert len(estado["regras"]) == len(regras.REGRAS_DEFAULT)
    assert regras.PATH.is_file()
    assert all(regra["origem"] == "predefinida" for regra in estado["regras"])
    assert all(regra["ativo"] for regra in estado["regras"])


def test_predefinicoes_reproduzem_a_logica_do_motor() -> None:
    ativas = {regra["id"]: regra for regra in regras.regras_ativas()}
    assert ativas["desvio_preco_alto"]["condicoes"][0] == {"campo": "ratio_base", "operador": ">", "valor": 1.2}
    assert ativas["aditivo_valor"]["condicoes"][0]["valor"] == 1.15
    assert ativas["publicacao_tardia"]["severidade"] == "aviso"
    # Ajuste direto atípico é uma regra **relativa** (compara com o global).
    condicoes = ativas["ajuste_direto_atipico"]["condicoes"]
    assert condicoes[1]["valor"] == {"campo": "taxa_ajuste_direto_global", "fator": 0.6}


def test_catalogo_de_campos_e_operadores() -> None:
    catalogo = regras.catalogo()
    campos = {campo["id"] for campo in catalogo["campos"]}
    assert {"valor", "ratio_base", "z_cpv", "taxa_ajuste_direto_global", "adjudicataria"} <= campos
    operadores = {operador["id"] for operador in catalogo["operadores"]}
    assert {">", "<", "==", "contem"} <= operadores
    assert {padrao["id"] for padrao in catalogo["padroes_nao_avaliaveis"]} >= {"contrato_atipico", "rede_pessoas"}
    # Os ids das regras e dos padrões não avaliáveis não podem colidir.
    ids_regras = {regra["id"] for regra in regras.listar()["regras"]}
    ids_padroes = {padrao["id"] for padrao in catalogo["padroes_nao_avaliaveis"]}
    assert not (ids_regras & ids_padroes)


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "invalida,esperado",
    [
        ({"label": "x", "condicoes": [{"campo": "inexistente", "operador": ">", "valor": 1}]}, "campo desconhecido"),
        ({"label": "x", "condicoes": [{"campo": "valor", "operador": "??", "valor": 1}]}, "operador desconhecido"),
        ({"label": "x", "condicoes": [{"campo": "valor", "operador": "contem", "valor": "a"}]}, "não se aplica"),
        ({"label": "x", "condicoes": []}, "pelo menos uma condição"),
        ({"label": "x", "condicoes": [{"campo": "valor", "operador": ">", "valor": "abc"}]}, "não numérico"),
        ({"label": "x", "modo": "talvez", "condicoes": [{"campo": "valor", "operador": ">", "valor": 1}]}, "modo"),
        ({"label": "x", "severidade": "urgente", "condicoes": [{"campo": "valor", "operador": ">", "valor": 1}]}, "severidade"),
        ({"label": "x", "condicoes": [{"campo": "ratio_base", "operador": ">", "valor": {"campo": "nada"}}]}, "campo de comparação"),
    ],
)
def test_validacao_recusa_regras_invalidas(invalida: dict, esperado: str) -> None:
    with pytest.raises(ValueError) as erro:
        regras.validar(invalida)
    assert esperado in str(erro.value)


def test_validacao_normaliza_numeros_e_texto() -> None:
    regra = regras.validar(
        {
            "label": "  Contrato grande  ",
            "condicoes": [
                {"campo": "valor", "operador": ">", "valor": "1500000"},
                {"campo": "procedimento", "operador": "contem", "valor": "Ajuste"},
            ],
        }
    )
    assert regra["label"] == "Contrato grande"
    assert regra["condicoes"][0]["valor"] == 1_500_000.0
    assert regra["condicoes"][1]["valor"] == "Ajuste"
    assert regra["id"] and regra["ativo"] is True


# ---------------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------------
def _contexto(**kwargs) -> dict:
    base = {
        "valor": 1000.0,
        "preco_base": 1000.0,
        "ratio_base": 1.0,
        "ratio_efetivo": 1.0,
        "dias_decisao": -20,
        "dias_assinatura": 5,
        "dias_publicacao": 10,
        "prazo_execucao": 30,
        "n_concorrentes": 5,
        "ajuste_direto": 0,
        "ano": 2023,
        "cpv": "45000000-7",
        "cpv_grupo": "45",
        "procedimento": "Concurso público",
        "adjudicante": "Município X",
        "adjudicataria": "Empresa A",
        "z_cpv": 0.0,
        "taxa_ajuste_direto_cpv": 0.6,
        "taxa_aditivo_cpv": 0.01,
        "taxa_ajuste_direto_global": 0.6,
        "contratos_do_cpv": 500,
    }
    base.update(kwargs)
    return base


def test_avaliacao_com_condicoes_em_e() -> None:
    ativas = regras.regras_ativas()
    # 1 concorrente em contrato de 25 000 € → cumpre «baixa_concorrencia» (E).
    hits = regras.avaliar(_contexto(n_concorrentes=1, valor=30_000), ativas)
    assert "baixa_concorrencia" in {hit["padrao"] for hit in hits}
    # 1 concorrente num contrato pequeno → não cumpre (o valor falha).
    hits = regras.avaliar(_contexto(n_concorrentes=1, valor=1000), ativas)
    assert "baixa_concorrencia" not in {hit["padrao"] for hit in hits}


def test_avaliacao_de_regra_relativa_ao_cpv() -> None:
    ativas = regras.regras_ativas()
    atipico = _contexto(ajuste_direto=1, taxa_ajuste_direto_cpv=0.1, taxa_ajuste_direto_global=0.6)
    normal = _contexto(ajuste_direto=1, taxa_ajuste_direto_cpv=0.6, taxa_ajuste_direto_global=0.6)
    assert "ajuste_direto_atipico" in {hit["padrao"] for hit in regras.avaliar(atipico, ativas)}
    assert "ajuste_direto_atipico" not in {hit["padrao"] for hit in regras.avaliar(normal, ativas)}


def test_avaliacao_ignora_campos_em_falta() -> None:
    """Sem dado não se conclui nada (não pode dar falso positivo)."""
    ativas = regras.regras_ativas()
    sem_dados = _contexto(ratio_base=None, dias_publicacao=None, n_concorrentes=None, z_cpv=None)
    assert regras.avaliar(sem_dados, ativas) == []


def test_detalhe_diz_o_campo_o_limite_e_o_valor() -> None:
    hit = next(
        item for item in regras.avaliar(_contexto(ratio_base=1.35), regras.regras_ativas()) if item["padrao"] == "desvio_preco_alto"
    )
    assert "1.2" in hit["detalhe"] and "1.35" in hit["detalhe"]
    assert hit["severidade"] == "aviso"


def test_modo_alguma_basta_uma_condicao() -> None:
    regra = regras.validar(
        {
            "label": "Valor alto ou sem concorrência",
            "modo": "alguma",
            "condicoes": [
                {"campo": "valor", "operador": ">", "valor": 1_000_000},
                {"campo": "n_concorrentes", "operador": "<=", "valor": 1},
            ],
        }
    )
    assert {hit["padrao"] for hit in regras.avaliar(_contexto(n_concorrentes=1), [regra])} == {regra["id"]}


# ---------------------------------------------------------------------------
# CRUD e templates
# ---------------------------------------------------------------------------
def test_criar_editar_alternar_duplicar_e_apagar() -> None:
    nova = regras.guardar(
        {
            "label": "Grandes contratos",
            "severidade": "alerta",
            "condicoes": [{"campo": "valor", "operador": ">", "valor": 5_000_000}],
        }
    )
    assert nova["id"].startswith("regra_") and nova["origem"] == "utilizador"

    editada = regras.guardar({**nova, "label": "Grandes contratos (5 M€)"})
    assert editada["id"] == nova["id"]
    assert editada["label"] == "Grandes contratos (5 M€)"
    assert sum(1 for regra in regras.listar()["regras"] if regra["id"] == nova["id"]) == 1

    assert regras.alternar(nova["id"])["ativo"] is False
    assert all(regra["id"] != nova["id"] for regra in regras.regras_ativas())

    copia = regras.duplicar(nova["id"])
    assert copia["id"] != nova["id"] and "cópia" in copia["label"]

    assert regras.apagar(copia["id"]) is True
    assert regras.apagar(copia["id"]) is False
    with pytest.raises(KeyError):
        regras.alternar("nao_existe")


def test_guardar_com_id_desconhecido_cria_regra_nova() -> None:
    nova = regras.guardar(
        {"id": "minha_regra", "label": "Minha regra", "condicoes": [{"campo": "valor", "operador": ">", "valor": 1}]}
    )
    assert nova["id"] == "minha_regra"
    outra = regras.guardar(
        {"id": "minha_regra", "label": "Outra", "condicoes": [{"campo": "valor", "operador": ">", "valor": 2}]}
    )
    assert outra["id"] == "minha_regra"


def test_templates_guardar_aplicar_e_apagar() -> None:
    template = regras.guardar_template({"nome": "Foco em preço", "regras": ["desvio_preco_alto", "aditivo_valor"]})
    assert template["id"].startswith("tpl_")
    aplicado = regras.aplicar_template(template["id"])
    assert set(aplicado["ativas"]) == {"desvio_preco_alto", "aditivo_valor"}
    ativas = {regra["id"] for regra in regras.regras_ativas()}
    assert ativas == {"desvio_preco_alto", "aditivo_valor"}
    assert regras.apagar_template(template["id"]) is True
    assert regras.apagar_template(template["id"]) is False


def test_templates_predefinidos_tem_regras_e_aplicam_se() -> None:
    """Bug apanhado na UI: os predefinidos usavam a chave `ativas`.

    Sem isto, aplicar um template predefinido não ligava regra nenhuma (e a
    interface rebentava ao ler `template.regras.length`).
    """
    predefinidos = [item for item in regras.listar()["templates"] if item.get("origem") == "predefinido"]
    assert len(predefinidos) == len(regras.TEMPLATES_DEFAULT)
    for template in predefinidos:
        assert isinstance(template.get("regras"), list) and template["regras"]

    essencial = next(item for item in predefinidos if item["id"] == "tpl_essencial")
    resultado = regras.aplicar_template("tpl_essencial")
    assert set(resultado["ativas"]) == set(essencial["regras"])
    assert {regra["id"] for regra in regras.regras_ativas()} == set(essencial["regras"])


def test_template_com_chave_antiga_migra_para_regras() -> None:
    regras.PATH.write_text(
        '{"regras": [], "templates": [{"id": "tpl_antigo", "nome": "Antigo", "ativas": ["aditivo_valor"]}]}',
        encoding="utf-8",
    )
    regras.reset_state_cache()
    template = regras.listar()["templates"][0]
    assert template["regras"] == ["aditivo_valor"]
    assert regras.aplicar_template("tpl_antigo")["ativas"] == ["aditivo_valor"]


def test_template_com_regra_desconhecida_e_recusado() -> None:
    with pytest.raises(ValueError) as erro:
        regras.guardar_template({"nome": "Mau", "regras": ["nao_existe"]})
    assert "desconhecidas" in str(erro.value)


def test_template_sem_nome_e_recusado() -> None:
    with pytest.raises(ValueError):
        regras.guardar_template({"nome": "  "})


def test_template_por_omissao_usa_as_regras_ativas() -> None:
    regras.alternar("aditivo_valor", False)
    template = regras.guardar_template({"nome": "Ativas agora"})
    assert "aditivo_valor" not in template["regras"]
    assert len(template["regras"]) == len(regras.regras_ativas())


def test_repor_predefinicoes_mantendo_personalizadas() -> None:
    regras.guardar({"label": "Minha", "id": "regra_minha", "condicoes": [{"campo": "valor", "operador": ">", "valor": 1}]})
    regras.alternar("aditivo_valor", False)
    regras.repor_default(manter_personalizadas=True)
    regras_por_id = {regra["id"]: regra for regra in regras.listar()["regras"]}
    assert "regra_minha" in regras_por_id
    assert regras_por_id["aditivo_valor"]["ativo"] is True
    assert regras_por_id["aditivo_valor"]["origem"] == "predefinida"


def test_repor_predefinicoes_de_fabrica_apaga_personalizadas() -> None:
    regras.guardar({"label": "Minha", "id": "regra_minha", "condicoes": [{"campo": "valor", "operador": ">", "valor": 1}]})
    regras.repor_default()
    ids = {regra["id"] for regra in regras.listar()["regras"]}
    assert "regra_minha" not in ids
    assert len(ids) == len(regras.REGRAS_DEFAULT)


def test_limite_de_regras() -> None:
    for indice in range(regras.MAX_REGRAS - len(regras.REGRAS_DEFAULT)):
        regras.guardar(
            {
                "id": f"extra_{indice}",
                "label": f"Extra {indice}",
                "condicoes": [{"campo": "valor", "operador": ">", "valor": indice + 1}],
            }
        )
    with pytest.raises(ValueError) as erro:
        regras.guardar({"label": "A mais", "condicoes": [{"campo": "valor", "operador": ">", "valor": 1}]})
    assert "limite" in str(erro.value)


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------
def test_estado_persiste_entre_leituras() -> None:
    regras.guardar({"label": "Persistente", "id": "regra_persistente", "condicoes": [{"campo": "valor", "operador": ">", "valor": 7}]})
    regras.reset_state_cache()
    assert "regra_persistente" in {regra["id"] for regra in regras.listar()["regras"]}


def test_ficheiro_corrompido_cai_nas_predefinicoes() -> None:
    regras.PATH.write_text("{ isto não é json", encoding="utf-8")
    regras.reset_state_cache()
    estado = regras.listar()
    assert len(estado["regras"]) == len(regras.REGRAS_DEFAULT)


def test_regras_invalidas_no_ficheiro_sao_ignoradas() -> None:
    regras.PATH.write_text(
        '{"regras": [{"id": "boa", "label": "Boa", "condicoes": [{"campo": "valor", "operador": ">", "valor": 1}]},'
        ' {"id": "ma", "label": "Má", "condicoes": [{"campo": "nada", "operador": ">", "valor": 1}]}], "templates": []}',
        encoding="utf-8",
    )
    regras.reset_state_cache()
    ids = {regra["id"] for regra in regras.listar()["regras"]}
    assert ids == {"boa"}


def test_resumo_regras_descreve_a_condicao() -> None:
    resumo = regras.resumo_regras(regras.listar()["regras"])
    por_id = {item["id"]: item for item in resumo}
    assert "Adjudicado ÷ preço base > 1.2" in por_id["desvio_preco_alto"]["condicao"]
    assert "E" in por_id["baixa_concorrencia"]["condicao"]
    assert "0.6 ×" in por_id["ajuste_direto_atipico"]["condicao"]
