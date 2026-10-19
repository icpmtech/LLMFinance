"""Testes da geografia do coletor do Racius.

O bloco da morada da ficha mostra o par «concelho, distrito» na maioria das
empresas, mas nas cidades mostra a **freguesia** no rótulo («Sé», «Funchal»).
Sem validar o par contra os 308 concelhos, `concelho` ficava com a freguesia e
as facetas/distritos da página do diretório saíam errados.
"""
from __future__ import annotations

import pytest

from collectors import racius


@pytest.mark.parametrize(
    ("label", "value", "esperado"),
    [
        # Rótulo é o concelho, valor é o distrito.
        ("Benavente", "Santarém", {"concelho": "Benavente", "distrito": "Santarém"}),
        ("Alcobaça", "Leiria", {"concelho": "Alcobaça", "distrito": "Leiria"}),
        ("Oeiras", "Lisboa", {"concelho": "Oeiras", "distrito": "Lisboa"}),
        ("Porto", "Porto", {"concelho": "Porto", "distrito": "Porto"}),
        ("Funchal", "Madeira", {"concelho": "Funchal", "distrito": "Madeira"}),
        # Rótulo é a freguesia, valor é o concelho.
        (
            "Sé",
            "Funchal",
            {"localidade": "Sé", "concelho": "Funchal", "distrito": "Madeira"},
        ),
        (
            "Oeiras e São Julião Barra",
            "Oeiras",
            {"localidade": "Oeiras e São Julião Barra", "concelho": "Oeiras", "distrito": "Lisboa"},
        ),
        # «Santa Cruz» é concelho na Madeira, mas aqui é a freguesia de Coimbra:
        # o valor (Coimbra) desempata.
        (
            "Santa Cruz",
            "Coimbra",
            {"localidade": "Santa Cruz", "concelho": "Coimbra", "distrito": "Coimbra"},
        ),
        # Par que não é geografia (a ficha não trazia o bloco da morada).
        ("Forma Jurídica", "Sociedade por Quotas", {}),
    ],
)
def test_resolve_geo(label, value, esperado):
    assert racius.resolve_geo(label, value) == esperado


def test_geo_a_partir_da_localizacao_da_lista():
    assert racius._geo_from_localizacao("Samora Correia, Benavente") == {
        "localidade": "Samora Correia",
        "concelho": "Benavente",
        "distrito": "Santarém",
    }
    assert racius._geo_from_localizacao("Fafe") == {"concelho": "Fafe", "distrito": "Braga"}
    assert racius._geo_from_localizacao("") == {}
    assert racius._geo_from_localizacao("Portugal") == {}


def test_slug_do_distrito_no_url():
    assert racius._slug("Porto") == "porto"
    assert racius._slug("Viana do Castelo") == "viana-do-castelo"
    assert racius._slug("Açores") == "acores"
    assert racius._slug("  Bragança ") == "braganca"


DETAIL_HTML = """
<ul>
  <li class="detail__detail">
    <p class="detail__key-info"> Morada</p><p class="t--d-blue"> Rua A 1, Sé</p>
    <p class="detail__key-info"> Sé</p><p class="t--d-blue"> Funchal</p>
  </li>
  <li class="detail__detail">
    <p class="detail__key-info"> Forma Jurídica</p><p class="t--d-blue"> Sociedade por Quotas</p>
    <p class="detail__key-info"> Capital Social</p><p class="t--d-blue"> 125.000,00</p>
  </li>
</ul>
"""

DETAIL_SEM_GEO = """
<ul>
  <li class="detail__detail">
    <p class="detail__key-info"> Morada</p><p class="t--d-blue"> Rua A 1</p>
    <p class="detail__key-info"> Forma Jurídica</p><p class="t--d-blue"> Sociedade por Quotas</p>
  </li>
</ul>
"""


def test_parse_detail_resolve_concelho_e_distrito():
    doc = racius.parse_detail(DETAIL_HTML)
    assert doc["concelho"] == "Funchal"
    assert doc["distrito"] == "Madeira"
    assert doc["localidade"] == "Sé"
    assert doc["forma_juridica"] == "Sociedade por Quotas"
    assert doc["capital_social_eur"] == 125000.0


def test_parse_detail_sem_geografia_nao_inventa_niveis():
    doc = racius.parse_detail(DETAIL_SEM_GEO)
    assert "concelho" not in doc
    assert "distrito" not in doc
    assert doc["forma_juridica"] == "Sociedade por Quotas"
