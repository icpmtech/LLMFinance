"""Exportação de contratos para Excel: as colunas ficam com a largura do conteúdo.

A largura era calculada com `max_length = val_length` (nome inexistente) dentro de
um `try/except Exception: pass`: o `NameError` era engolido, `max_length` ficava
sempre a 0 e **todas** as colunas saíam com 2 de largura. O teste garante que a
coluna acompanha o texto mais longo (limitada a 60) e que a linha de cabeçalho
continua a contar.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

openpyxl = pytest.importorskip("openpyxl")

from api.es.contratos import export_contracts_to_excel  # noqa: E402
from api.es.indices import CONTRACTS_INDEX  # noqa: E402

LONGO = "Aquisição de serviços de manutenção preventiva e corretiva dos equipamentos"


class _Resp:
    """Resposta como a do cliente ES (`resp["hits"]["hits"][i]["_source"]`)."""

    def __init__(self, hits: List[Dict[str, Any]]) -> None:
        self._hits = hits

    def __getitem__(self, chave: str) -> Any:
        if chave != "hits":
            raise KeyError(chave)
        return {"hits": self._hits}


class _ClienteFalso:
    """Cliente mínimo: devolve os contratos pedidos e regista a consulta."""

    def __init__(self, contratos: List[Dict[str, Any]]) -> None:
        self.contratos = contratos
        self.consultas: List[Dict[str, Any]] = []

    def search(self, *, index: str, body: Dict[str, Any]) -> _Resp:
        self.consultas.append({"index": index, "body": body})
        return _Resp([{"_source": contrato} for contrato in self.contratos])


def _contrato(**extra: Any) -> Dict[str, Any]:
    base = {
        "idcontrato": "15755195",
        "Ano": 2026,
        "tipoContrato": "Aquisição de serviços",
        "objectoContrato": LONGO,
        "precoContratual": 1234.5,
        "dataPublicacao": "2026-10-21",
        "adjudicantes": {"parsed": [{"nome": "Unidade Local de Saúde de Santa Maria", "nif": "508481287"}]},
        "adjudicatarios": {"parsed": [{"nome": "Fornecedor, Lda.", "nif": "500000000"}]},
    }
    base.update(extra)
    return base


def _abrir(payload: bytes):
    return openpyxl.load_workbook(io.BytesIO(payload))


def test_largura_das_colunas_acompanha_o_conteudo() -> None:
    cliente = _ClienteFalso([_contrato()])

    livro = _abrir(export_contracts_to_excel(es=cliente))
    folha = livro["Contratos"]

    larguras = {letra: dim.width for letra, dim in folha.column_dimensions.items()}
    assert larguras, "nenhuma coluna ficou com largura definida"
    # Antes da correção todas as colunas ficavam com 2 (0 + 2).
    assert max(larguras.values()) > 2, f"as colunas continuam todas estreitas: {larguras}"

    # A coluna do objecto (texto longo) é a mais larga, capada a 60.
    cabecalho = [celula.value for celula in folha[1]]
    coluna_objecto = openpyxl.utils.get_column_letter(cabecalho.index("objectoContrato") + 1)
    assert folha.column_dimensions[coluna_objecto].width == 60

    # Uma coluna curta segue o conteúdo mais longo (cabeçalho «Ano» ou o valor
    # «2026»), sem herdar a largura da coluna longa.
    coluna_ano = openpyxl.utils.get_column_letter(cabecalho.index("Ano") + 1)
    assert folha.column_dimensions[coluna_ano].width == max(len("Ano"), len("2026")) + 2


def test_largura_tem_em_conta_o_cabecalho() -> None:
    """Sem linhas de dados, a largura vem do cabeçalho (e não dos 2 por omissão)."""
    cliente = _ClienteFalso([])

    folha = _abrir(export_contracts_to_excel(es=cliente))["Contratos"]

    cabecalho = [celula.value for celula in folha[1]]
    for celula in folha[1]:
        letra = celula.column_letter
        esperado = min(len(str(celula.value)) + 2, 60)
        assert folha.column_dimensions[letra].width == esperado, celula.value
    assert cabecalho, "a folha devia ter cabeçalho mesmo sem contratos"


def test_exportacao_mantem_a_pesquisa_no_indice_de_contratos() -> None:
    cliente = _ClienteFalso([_contrato()])

    export_contracts_to_excel(q="manutenção", year=2026, es=cliente)

    assert cliente.consultas and cliente.consultas[0]["index"] == CONTRACTS_INDEX
    corpo = cliente.consultas[0]["body"]
    assert corpo["size"] == 10000  # limite por omissão de `max_records`
    assert corpo["query"], "a exportação tem de levar a query dos filtros"
