"""Subvenções públicas (Lei n.º 64/2013, de 27/08).

O que se testa aqui é o que **não** depende da rede nem do Elasticsearch: a
leitura anual dos `.ods` da IGF (cabeçalho em duas linhas, colunas repetidas e
tapadas por `span`, anos na pasta ou no nome do ficheiro), a normalização de
valores (montantes em formato português, datas ISO/serie do ODF, NIF de
beneficiário estrangeiro com a letra «E») e o manifesto do que já foi lido.

Os ficheiros reais têm ~200 mil linhas cada; os testes usam `.ods` sintéticos,
construídos aqui mesmo, para serem rápidos e determinísticos.
"""
from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import pytest

from api import subvencoes_service as subvencoes

# Namespaces do ODF usados pelos `.ods` de teste.
T = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
O = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
X = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"


def _celula(valor: str, *, valor_tipado: str | None = None, repetidas: int = 1, tapadas: int = 1) -> str:
    """Uma célula de `table:table-cell` (texto simples ou valor tipado)."""
    atributos = [f'table:number-columns-repeated="{repetidas}"'] if repetidas > 1 else []
    if tapadas > 1:
        atributos.append(f'table:number-columns-spanned="{tapadas}"')
    if valor_tipado is not None:
        atributos.append(f'office:value="{valor_tipado}"')
    prefixo = (" " + " ".join(atributos)) if atributos else ""
    if not valor:
        return f"<table:table-cell{prefixo}/>"
    return (
        f"<table:table-cell{prefixo}><text:p>{valor}</text:p></table:table-cell>"
    )


def _linha(celulas: list[str], *, repetidas: int = 1) -> str:
    atributo = f' table:number-rows-repeated="{repetidas}"' if repetidas > 1 else ""
    return f"<table:table-row{atributo}>{''.join(celulas)}</table:table-row>"


def _escrever_ods(path: Path, folha: str, linhas: list[str]) -> Path:
    """Grava um `.ods` mínimo (o leitor só lê o `content.xml`)."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content xmlns:office="{O}" xmlns:table="{T}" xmlns:text="{X}">'
        "<office:body><office:spreadsheet>"
        f'<table:table table:name="{folha}">'
        + "".join(linhas)
        + "</table:table></office:spreadsheet></office:body></office:document-content>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        zf.writestr("content.xml", xml)
    return path


#: Cabeçalho igual ao dos ficheiros da IGF: 7 rótulos e, por baixo, as três
#: colunas em que «FUNDAMENTO LEGAL» se subdivide.
CABECALHO = [
    _linha(
        [
            _celula("LISTAGEM DAS SUBVENÇÕES E OUTROS BENEFÍCIOS PÚBLICOS (ANO 2025)"),
            _celula("", repetidas=9),
        ]
    ),
    _linha([_celula("Notas:"), _celula("", repetidas=9)]),
    _linha([_celula("a) A informação publicitada foi prestada pelas entidades."), _celula("", repetidas=9)]),
    _linha(
        [
            _celula("NIF (EO)"),
            _celula("ENTIDADE OBRIGADA (EO)"),
            _celula("NIF (B)"),
            _celula("BENEFICIÁRIO (B)"),
            _celula("MONTANTE TRANSFERIDO OU BENEFÍCIO AUFERIDO (euros)"),
            _celula("DATA DA DECISÃO"),
            _celula("FINALIDADE"),
            _celula("FUNDAMENTO LEGAL", tapadas=3),
        ]
    ),
    _linha(
        [
            _celula("", repetidas=7),
            _celula("TIPO DE ATO"),
            _celula("N.º"),
            _celula("DATA"),
        ]
    ),
]


def _linha_dados(
    *,
    nif_entidade: str = "500051054",
    entidade: str = "MUNICÍPIO DE ALMADA",
    nif_beneficiario: str = "510557260",
    beneficiario: str = "ACADEMIA SHOWIT",
    montante: str = "12825",
    data_decisao: str = "2025-07-21",
    finalidade: str = "Programa Municipal",
    tipo_ato: str = "Lei",
    numero_ato: str = "75",
    data_ato: str = "2013-09-12",
) -> str:
    return _linha(
        [
            _celula(nif_entidade),
            _celula(entidade),
            _celula(nif_beneficiario),
            _celula(beneficiario),
            _celula(montante, valor_tipado=montante),
            _celula(data_decisao, valor_tipado=data_decisao),
            _celula(finalidade),
            _celula(tipo_ato),
            _celula(numero_ato),
            _celula(data_ato, valor_tipado=data_ato),
        ]
    )


@pytest.fixture()
def pasta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pasta de dados temporária (nada toca em `data/subvencoes`)."""
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    return tmp_path


def _dois_ficheiros(base: Path) -> None:
    """Um ano em subpasta e outro no nome do ficheiro — como na pasta real."""
    _escrever_ods(
        base / "2024" / "lista-subvpublicas2024.ods",
        "Subv_2024",
        CABECALHO
        + [
            _linha_dados(montante="1000", data_decisao="2024-03-04", nif_beneficiario="500000001"),
            _linha_dados(montante="2345.67", data_decisao="2024-05-06", nif_beneficiario="500000002"),
            _linha([]),  # linha vazia: ignorada
        ],
    )
    _escrever_ods(
        base / "lista-subvpublicas2025_1.ods",
        "Subv_2025",
        CABECALHO + [_linha_dados(montante="19706,84", data_decisao="21/07/2025")],
    )


# --------------------------------------------------------------------- anos


def test_ano_vem_da_subpasta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)
    itens = {item["rel_path"]: item for item in subvencoes.ficheiros()}
    assert itens["2024/lista-subvpublicas2024.ods"]["ano"] == 2024
    assert itens["2024/lista-subvpublicas2024.ods"]["ano_origem"] == "pasta"
    assert itens["lista-subvpublicas2025_1.ods"]["ano"] == 2025
    assert itens["lista-subvpublicas2025_1.ods"]["ano_origem"] == "nome"


def test_ficheiro_sem_ano_fica_sem_ano(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _escrever_ods(tmp_path / "subvencoes.ods", "Subv", CABECALHO + [_linha_dados()])
    itens = subvencoes.ficheiros()
    assert len(itens) == 1
    assert itens[0]["ano"] is None


def test_pasta_normalizada_nao_e_lida_como_origem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)
    subvencoes.normalized_dir().mkdir(parents=True, exist_ok=True)
    (subvencoes.normalized_dir() / "subv-2024.jsonl").write_text("{}\n", encoding="utf-8")
    assert all(item["rel_path"].startswith("_normalized") is False for item in subvencoes.ficheiros())


# ------------------------------------------------------- normalização de valores


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("12825", 12825.0),
        ("19706.849999999999", 19706.85),
        ("1.234,56", 1234.56),
        ("1 234,56 €", 1234.56),
        ("1,234.56", 1234.56),
        ("", None),
        ("não é número", None),
    ],
)
def test_para_float(entrada: str, esperado: float | None) -> None:
    assert subvencoes.para_float(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("2025-07-21T00:00:00", "2025-07-21"),
        ("2025-07-21", "2025-07-21"),
        ("21/07/2025", "2025-07-21"),
        ("4/3/2024", "2024-03-04"),
        ("", None),
        ("sem data", None),
    ],
)
def test_para_data(entrada: str, esperado: str | None) -> None:
    assert subvencoes.para_data(entrada) == esperado


def test_nif_de_beneficiario_estrangeiro() -> None:
    """A nota b) do ficheiro acrescenta a letra «E» aos beneficiários estrangeiros."""
    assert subvencoes.limpar_nif_beneficiario("123456789E") == ("123456789", True)
    assert subvencoes.limpar_nif_beneficiario("E123456789") == ("123456789", True)
    assert subvencoes.limpar_nif_beneficiario("510557260") == ("510557260", False)
    assert subvencoes.limpar_nif_beneficiario("123") == ("", False)


def test_tipo_de_beneficiario_pelo_prefixo_do_nif() -> None:
    assert subvencoes.tipo_beneficiario("123456789") == "pessoa_singular"
    assert subvencoes.tipo_beneficiario("510557260") == "pessoa_coletiva"
    assert subvencoes.tipo_beneficiario("500051054") == "pessoa_coletiva"
    assert subvencoes.tipo_beneficiario("680017763") == "entidade_publica"
    assert subvencoes.tipo_beneficiario("800000000") == "empresario_individual"
    assert subvencoes.tipo_beneficiario("900000000") == "outro"
    assert subvencoes.tipo_beneficiario("") is None


def test_fundamento_legal_composto() -> None:
    assert subvencoes.fundamento_legal("Lei", "75") == "Lei n.º 75"
    assert subvencoes.fundamento_legal("Lei", None) == "Lei"
    assert subvencoes.fundamento_legal(None, None) is None


# ------------------------------------------------------------------- leitura


def test_mapa_de_colunas_do_cabecalho_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O cabeçalho em duas linhas mapeia nas 10 colunas, pela ordem certa."""
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    ficheiro = _escrever_ods(tmp_path / "lista-2025.ods", "Subv_2025", CABECALHO + [_linha_dados()])
    bruto = next(iter(subvencoes._iter_registos(ficheiro)))
    assert bruto["indices"] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert bruto["folha"] == "Subv_2025"


def test_le_um_ficheiro_e_normaliza_as_linhas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    ficheiro = _escrever_ods(
        tmp_path / "2025" / "lista-subvpublicas2025_1.ods",
        "Subv_2025",
        CABECALHO
        + [
            _linha_dados(montante="19706.849999999999", nif_beneficiario="513306358"),
            _linha_dados(montante="3000", nif_beneficiario="510557260"),
            _linha([_celula("", repetidas=10)]),
        ],
    )
    lote = subvencoes.ler_ficheiro(ficheiro, 2025)
    assert lote["ano"] == 2025
    assert lote["folha"] == "Subv_2025"
    assert lote["registos"] == 2
    assert lote["montante_total"] == 22706.85
    assert lote["primeira_decisao"] == "2025-07-21"
    assert lote["ultima_decisao"] == "2025-07-21"
    assert lote["sha256"] and lote["bytes"] > 0

    registos = [
        json.loads(linha_) for linha_ in subvencoes.jsonl_path(lote).read_text(encoding="utf-8").splitlines()
    ]
    assert [registo["doc_id"] for registo in registos] == ["2025:6", "2025:7"]
    primeiro = registos[0]
    assert primeiro["entidade"] == "MUNICÍPIO DE ALMADA"
    assert primeiro["beneficiario"] == "ACADEMIA SHOWIT"
    assert primeiro["beneficiario_tipo"] == "pessoa_coletiva"
    assert primeiro["beneficiario_estrangeiro"] is False
    assert primeiro["montante"] == 19706.85
    assert primeiro["data_decisao"] == "2025-07-21"
    assert primeiro["ano_decisao"] == 2025
    assert primeiro["fundamento_legal"] == "Lei n.º 75"
    assert primeiro["data_ato"] == "2013-09-12"
    assert primeiro["finalidade"] == "Programa Municipal"


def test_valores_repetidos_e_tapados_nao_desalinham_colunas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Células vazias repetidas e `span` a meio da linha mantêm as posições."""
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    linha = _linha(
        [
            _celula("500051054"),
            _celula("MUNICÍPIO DE ALMADA"),
            _celula("", repetidas=2),  # duas colunas vazias: NIF (B) e BENEFICIÁRIO
            _celula("2500", valor_tipado="2500"),
            _celula("2025-02-03", valor_tipado="2025-02-03"),
            _celula("Apoio", tapadas=2),  # FINALIDADE ocupa duas colunas no ficheiro
            _celula("Lei"),
            _celula("75"),
            _celula("2013-09-12", valor_tipado="2013-09-12"),
        ]
    )
    ficheiro = _escrever_ods(tmp_path / "2025" / "x.ods", "Subv_2025", CABECALHO + [linha])
    lote = subvencoes.ler_ficheiro(ficheiro, 2025)
    assert lote["registos"] == 1
    registos = [
        json.loads(linha_) for linha_ in subvencoes.jsonl_path(lote).read_text(encoding="utf-8").splitlines()
    ]
    registo = registos[0]
    assert registo["nif_beneficiario"] is None
    assert registo["beneficiario"] is None
    assert registo["montante"] == 2500.0
    assert registo["data_decisao"] == "2025-02-03"
    assert registo["finalidade"] == "Apoio"


def test_ano_vem_da_folha_quando_nao_ha_pasta_nem_nome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    ficheiro = _escrever_ods(tmp_path / "subv.ods", "Subv_2023", CABECALHO + [_linha_dados()])
    assert subvencoes.ficheiros()[0]["ano"] is None
    lote = subvencoes.ler_ficheiro(ficheiro, None)
    assert lote["ano"] == 2023


# --------------------------------------------------------- ler a pasta por ano


def test_ler_pasta_por_ano_e_manifesto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)

    resultado = subvencoes.ler_pasta()
    assert resultado["ficheiros"] == 2
    assert resultado["lidos_total"] == 2
    assert resultado["reutilizados_total"] == 0
    assert resultado["registos"] == 3
    assert resultado["montante"] == round(1000 + 2345.67 + 19706.84, 2)
    assert resultado["erros"] == []

    anos = {lote["rel_path"]: lote["ano"] for lote in resultado["lidos"]}
    assert anos == {"2024/lista-subvpublicas2024.ods": 2024, "lista-subvpublicas2025_1.ods": 2025}

    manifesto = subvencoes.read_manifest()
    assert set(manifesto["lotes"]) == {"2024/lista-subvpublicas2024.ods", "lista-subvpublicas2025_1.ods"}
    assert manifesto["atualizado_em"]

    # Um ano só: filtra pela subpasta.
    assert subvencoes.ler_pasta([2024])["registos"] == 2


def test_ler_pasta_reaproveita_o_que_ja_esta_lido(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem alterações ao ficheiro, a 2.ª leitura não volta a ler ~200 mil linhas."""
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)
    subvencoes.ler_pasta()

    segunda = subvencoes.ler_pasta()
    assert segunda["lidos_total"] == 0
    assert segunda["reutilizados_total"] == 2
    assert segunda["registos"] == 3

    forcada = subvencoes.ler_pasta(forcar=True)
    assert forcada["lidos_total"] == 2


def test_manifesto_guarda_nome_relativo_e_resolve_em_qualquer_pasta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O manifesto não pode guardar caminhos absolutos.

    A mesma pasta é lida do anfitrião (`C:\\…`) e de dentro do contentor
    (`/app/…`); um caminho absoluto gravado num dos lados não existe no outro —
    foi o que fez o painel do Docker mostrar «0 registos / 1 por ler».
    """
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)
    resultado = subvencoes.ler_pasta()

    primeiro = resultado["lidos"][0]
    assert "jsonl" in primeiro
    assert Path(primeiro["jsonl"]).is_absolute() is False
    assert primeiro["jsonl"].endswith(".jsonl")

    # Caminho absoluto de outro sistema operativo: resolve pelo nome.
    assert subvencoes.jsonl_path({"jsonl_path": "C:\\outro\\sitio\\subv-x.jsonl"}) == (
        subvencoes.normalized_dir() / "subv-x.jsonl"
    )
    assert subvencoes.jsonl_path({"jsonl_path": "/app/data/subvencoes/_normalized/subv-y.jsonl"}) == (
        subvencoes.normalized_dir() / "subv-y.jsonl"
    )
    # Lote sem JSONL: `None`, e nunca o diretório atual (`Path("")`).
    assert subvencoes.jsonl_path({}) is None
    assert subvencoes.tem_jsonl({}) is False

    # O manifesto em disco não guarda caminhos absolutos.
    bruto = json.loads((subvencoes.data_dir() / "_manifest.json").read_text(encoding="utf-8"))
    for lote in bruto["lotes"].values():
        assert "jsonl_path" not in lote, lote
        assert Path(lote["jsonl"]).is_absolute() is False

    # E o `meta` volta a ver os lotes como lidos.
    meta = subvencoes.meta()
    assert meta["lidos"] == 2
    assert meta["registos_lidos"] == 3
    assert all(item["pendentes"] == 0 for item in meta["anos"])


@pytest.mark.parametrize(
    "guardado",
    [
        "C:\\LLMFinance\\finance-llm\\data\\subvencoes\\_normalized\\subv-a.jsonl",
        "/app/data/subvencoes/_normalized/subv-a.jsonl",
        "subv-a.jsonl",
        "_normalized/subv-a.jsonl",
    ],
)
def test_jsonl_resolve_sempre_para_a_pasta_normalizada(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, guardado: str) -> None:
    """Seja qual for a forma guardada, o JSONL é procurado em `_normalized/`."""
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    assert subvencoes.jsonl_path({"jsonl_path": guardado}) == (subvencoes.normalized_dir() / "subv-a.jsonl")


def test_apagar_o_jsonl_obriga_a_reler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)
    subvencoes.ler_pasta()
    for caminho in subvencoes.normalized_dir().glob("*.jsonl"):
        caminho.unlink()
    resultado = subvencoes.ler_pasta()
    assert resultado["lidos_total"] == 2


def test_listar_lotes_agrupa_por_ano(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)
    subvencoes.ler_pasta()
    lotes = subvencoes.listar_lotes()
    assert lotes["total"] == 2
    assert lotes["registos"] == 3
    assert [item["ano"] for item in lotes["por_ano"]] == [2025, 2024]
    assert lotes["por_ano"][0]["registos"] == 1


def test_preview_le_o_jsonl_do_ano(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)
    subvencoes.ler_pasta()
    amostra = subvencoes.preview(2024, limite=1)
    assert amostra["total"] == 2
    assert len(amostra["items"]) == 1
    assert amostra["items"][0]["ano"] == 2024
    assert subvencoes.preview(2030)["total"] == 0


def test_meta_conta_pendentes_e_anos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)

    antes = subvencoes.meta()
    assert antes["ficheiros_disco"] == 2
    assert antes["registos_lidos"] == 0
    assert {item["ano"]: item["pendentes"] for item in antes["anos"]} == {2025: 1, 2024: 1}

    subvencoes.ler_pasta()
    depois = subvencoes.meta()
    assert depois["lidos"] == 2
    assert depois["registos_lidos"] == 3
    assert {item["ano"]: item["pendentes"] for item in depois["anos"]} == {2025: 0, 2024: 0}
    assert depois["index"] == "finance_subvencoes"
    assert [coluna["campo"] for coluna in depois["colunas"]][:4] == [
        "nif_entidade",
        "entidade",
        "nif_beneficiario",
        "beneficiario",
    ]


def test_ficheiro_corrompido_nao_trava_os_restantes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)
    (tmp_path / "2025" / "mau.ods").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "2025" / "mau.ods").write_bytes(b"isto nao e um zip")
    resultado = subvencoes.ler_pasta()
    assert resultado["lidos_total"] == 2
    assert len(resultado["erros"]) == 1
    assert resultado["erros"][0]["rel_path"] == "2025/mau.ods"


# -------------------------------------------------- sem Elasticsearch disponível


def test_indexar_sem_elasticsearch_nao_rebenta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.elasticsearch_client.get_es_client", lambda *_, **__: None)
    resultado = subvencoes.indexar()
    assert "Elasticsearch" in str(resultado.get("error"))
    assert resultado["indexados"] == 0


def test_pesquisa_sem_elasticsearch_nao_rebenta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.elasticsearch_client.get_es_client", lambda *_, **__: None)
    resultado = subvencoes.search(q="teatro", ano=2025)
    assert "Elasticsearch" in str(resultado.get("error"))
    assert resultado["items"] == [] and resultado["total"] == 0


def test_resumo_e_fichas_sem_elasticsearch_nao_rebentam(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.elasticsearch_client.get_es_client", lambda *_, **__: None)
    assert "Elasticsearch" in str(subvencoes.resumo().get("error"))
    assert subvencoes.por_beneficiario("500051054")["items"] == []
    assert subvencoes.por_entidade("500051054")["items"] == []


# -------------------------------------------------------------- trabalhos (jobs)


def test_job_desconhecido_e_recusado() -> None:
    with pytest.raises(ValueError):
        subvencoes.start_job("apagar-tudo")


def test_ler_pasta_em_segundo_plano(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O trabalho «ler» corre e o estado fica consultável."""
    monkeypatch.setenv(subvencoes.DATA_DIR_ENV, str(tmp_path))
    _dois_ficheiros(tmp_path)

    job = subvencoes.start_job("ler", {})
    assert job["tipo"] == "ler"
    assert job["progress"]["phase"] == "a começar"

    # O trabalho corre numa thread: esperar (com pausa) até terminar.
    for _ in range(200):
        time.sleep(0.05)
        atual = subvencoes.job_status(job["job_id"])
        assert atual is not None
        if atual["status"] != "running":
            break

    assert atual["status"] == "done"
    assert atual["result"]["registos"] == 3
    assert subvencoes.list_jobs()["total"] >= 1
    assert subvencoes.job_status("inexistente") is None
