"""Põe na loja o catálogo de rádios Baofeng e de kits de sobrevivência.

Os dois grupos são comprados na AliExpress e na Temu e revendidos com expedição
direta do fornecedor («dropshipping» dentro da União Europeia): os produtos
nascem com stock a zero e sob encomenda, guardam o custo estimado em `cost` e o
preço é 2,5 vezes esse custo, com o IVA de 23% incluído como no resto da loja.

`data/shop/shop.json` não é versionado, por isso é este script que leva o
catálogo a uma instalação nova ou já em uso. Passa sempre pela API do
`shop_store`, para a criação ficar na atividade e nas revisões da loja, como
qualquer alteração feita na gestão. No fim liga a cada produto a imagem de marca
que viaja com o código (`api/site_assets/`, biblioteca de media do CMS).

    python _criar_produtos_radios_sobrevivencia.py
    python _criar_produtos_radios_sobrevivencia.py --atualizar

Sem `--atualizar`, o que já existir (procurado pelo `slug`) fica como está, para
não desfazer escolhas feitas na loja. Com `--atualizar`, os campos definidos aqui
são repostos. Pode ser corrido as vezes que forem precisas.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

from api import shop_store as store

AUTOR = "catalogo@iqos.pt"

#: O preço de venda é este múltiplo do custo estimado no fornecedor.
MULTIPLICADOR = 2.5

#: Prazo que acompanha todos os produtos (expedição direta do fornecedor na UE).
PRAZO = "**Entrega em 10 a 20 dias úteis**, por expedição direta do fornecedor na União Europeia."

NOTA_LEGAL_RADIOS = (
    "> **Nota legal:** fora da banda PMR446, a utilização em Portugal carece de licença "
    "de radiocomunicações da ANACOM. A venda não confere direito de utilização."
)

CATEGORIAS: List[Dict[str, Any]] = [
    {
        "name": "Rádios e Comunicações",
        "slug": "radios-comunicacoes",
        "description": "Walkie-talkies e rádios Baofeng para equipas, campo e emergência.",
        "featured": True,
        "order": 5,
    },
    {
        "name": "Kits de Sobrevivência",
        "slug": "kits-sobrevivencia",
        "description": "Kits de emergência e sobrevivência para casa, viagem e campo.",
        "featured": True,
        "order": 6,
    },
]

PRODUTOS: List[Dict[str, Any]] = [
    {
        "name": "Rádio Baofeng UV-5R — dupla banda VHF/UHF",
        "slug": "radio-baofeng-uv-5r",
        "sku": "BF-UV5R",
        "category": "radios-comunicacoes",
        "cost": 16.0,
        "featured": True,
        "order": 20,
        "short_description": "Walkie-talkie de dupla banda, 128 canais e 8 W tri-power. O modelo mais vendido da Baofeng, com bateria de 1800 mAh e carregador de dock.",
        "description": (
            "## O que inclui\n\n"
            "- Rádio Baofeng UV-5R\n"
            "- Bateria de lítio 1800 mAh\n"
            "- Carregador de dock\n"
            "- Antena original, presilha de cinto e auscultador com PTT\n\n"
            "## Características\n\n"
            "- Dupla banda: 144–146 MHz e 430–440 MHz\n"
            "- Tri-power: 8 W, 4 W e 1 W, selecionáveis\n"
            "- 128 canais, teclado numérico e programação por cabo (não incluído)\n"
            "- Ecrã LCD iluminado, lanterna LED e alarme de emergência\n\n"
            f"{PRAZO}\n\n{NOTA_LEGAL_RADIOS}"
        ),
        "tags": ["baofeng", "uv-5r", "rádio", "walkie-talkie", "vhf", "uhf"],
        "attributes": [
            {"label": "Bandas", "value": "144–146 MHz / 430–440 MHz"},
            {"label": "Potência", "value": "8 W tri-power"},
            {"label": "Canais", "value": "128"},
            {"label": "Bateria", "value": "1800 mAh"},
        ],
        "weight_kg": 0.45,
        "length_cm": 20.0,
        "width_cm": 12.0,
        "height_cm": 8.0,
        "internal_notes": "Origem: AliExpress (dropshipping UE). Foto e ficha seguem o anúncio 1005007038745274 («1/2X Baofeng UV-5R 8W Tri-Power ... 1800mAh»). Custo estimado 16,00 €; preço a 2,5× o custo. Confirmar oferta do fornecedor antes de cada reposição.",
    },
    {
        "name": "Rádio Baofeng UV-5R — kit com auscultador e antena de ganho",
        "slug": "radio-baofeng-uv-5r-kit-auscultador-antena",
        "sku": "BF-UV5R-KIT",
        "category": "radios-comunicacoes",
        "cost": 21.0,
        "order": 21,
        "short_description": "O UV-5R com auscultador com PTT, antena de ganho de 15 cm e carregador de dock: pronto a usar em campo.",
        "description": (
            "## O que inclui\n\n"
            "- Rádio Baofeng UV-5R\n"
            "- Auscultador com microfone e PTT\n"
            "- Antena de ganho de 15 cm (além da original)\n"
            "- Bateria de lítio 1800 mAh e carregador de dock\n"
            "- Presilha de cinto e cordão\n\n"
            "A antena de ganho melhora o alcance em zonas de relevo e a auscultador deixa "
            "as mãos livres, com o PTT preso ao colete ou à mochila.\n\n"
            f"{PRAZO}\n\n{NOTA_LEGAL_RADIOS}"
        ),
        "tags": ["baofeng", "uv-5r", "kit", "auscultador", "antena", "walkie-talkie"],
        "attributes": [
            {"label": "Inclui", "value": "Rádio, auscultador, antena de ganho, carregador"},
            {"label": "Bandas", "value": "144–146 MHz / 430–440 MHz"},
            {"label": "Potência", "value": "5 W"},
            {"label": "Bateria", "value": "1800 mAh"},
        ],
        "weight_kg": 0.65,
        "length_cm": 22.0,
        "width_cm": 14.0,
        "height_cm": 9.0,
        "internal_notes": "Origem: AliExpress (dropshipping UE). Custo estimado 21,00 €; preço a 2,5× o custo. Confirmar oferta do fornecedor antes de cada reposição.",
    },
    {
        "name": "Rádio Baofeng UV-82 — dupla banda 8 W",
        "slug": "radio-baofeng-uv-82",
        "sku": "BF-UV82",
        "category": "radios-comunicacoes",
        "cost": 25.0,
        "order": 22,
        "short_description": "Dupla banda com 8 W, dois botões PTT e 128 canais. Mais alcance do que o UV-5R, com a mesma bateria de 1800 mAh.",
        "description": (
            "## O que inclui\n\n"
            "- Rádio Baofeng UV-82\n"
            "- Bateria de lítio 1800 mAh\n"
            "- Carregador de dock\n"
            "- Antena, presilha de cinto e auscultador com PTT\n\n"
            "## Características\n\n"
            "- Dupla banda: 144–146 MHz e 430–440 MHz\n"
            "- 8 W de potência de transmissão\n"
            "- Dois PTT (superior e lateral) para grupos diferentes\n"
            "- 128 canais, VFO e programação por cabo (não incluído)\n\n"
            f"{PRAZO}\n\n{NOTA_LEGAL_RADIOS}"
        ),
        "tags": ["baofeng", "uv-82", "rádio", "walkie-talkie", "8w", "dupla-banda"],
        "attributes": [
            {"label": "Bandas", "value": "144–146 MHz / 430–440 MHz"},
            {"label": "Potência", "value": "8 W"},
            {"label": "Canais", "value": "128"},
            {"label": "Bateria", "value": "1800 mAh"},
            {"label": "Carregamento", "value": "USB Type-C"},
        ],
        "weight_kg": 0.55,
        "length_cm": 21.0,
        "width_cm": 13.0,
        "height_cm": 8.0,
        "internal_notes": "Origem: AliExpress (dropshipping UE). Foto e ficha seguem o anúncio 1005013082136842 («Baofeng UV-82 5W 8W ... Tipo-C, PTT Duplo»). Custo estimado 25,00 €; preço a 2,5× o custo. Confirmar oferta do fornecedor antes de cada reposição.",
    },
    {
        "name": "Rádio Baofeng BF-888S — pack de 2",
        "slug": "radio-baofeng-bf-888s-pack-2",
        "sku": "BF-888S-2",
        "category": "radios-comunicacoes",
        "cost": 22.0,
        "order": 23,
        "short_description": "Dois walkie-talkies UHF de 16 canais, com carregadores e auscultadores. A escolha económica para equipas.",
        "description": (
            "## O que inclui\n\n"
            "- 2 rádios Baofeng BF-888S\n"
            "- 2 carregadores de dock\n"
            "- 2 auscultadores com PTT\n"
            "- 2 presilhas de cinto\n\n"
            "## Características\n\n"
            "- Banda UHF: 400–470 MHz\n"
            "- 16 canais pré-programados, potência de 2 W\n"
            "- Bateria de 1500 mAh, com cerca de 8 horas de uso\n"
            "- Lanterna LED integrada\n\n"
            "Pensado para equipas pequenas — obras, eventos, armazém, segurança ou campo. "
            "A reprogramação dos canais faz-se por cabo (não incluído).\n\n"
            f"{PRAZO}\n\n{NOTA_LEGAL_RADIOS}"
        ),
        "tags": ["baofeng", "bf-888s", "pack-2", "walkie-talkie", "uhf", "equipas"],
        "attributes": [
            {"label": "Inclui", "value": "2 rádios, 2 carregadores, 2 auscultadores"},
            {"label": "Banda", "value": "UHF 400–470 MHz"},
            {"label": "Potência", "value": "2 W"},
            {"label": "Canais", "value": "16"},
        ],
        "weight_kg": 1.0,
        "length_cm": 26.0,
        "width_cm": 18.0,
        "height_cm": 10.0,
        "internal_notes": "Origem: AliExpress (dropshipping UE). Custo estimado 22,00 €; preço a 2,5× o custo. Confirmar oferta do fornecedor antes de cada reposição.",
    },
    {
        "name": "Rádio Baofeng UV-9R Plus — à prova de água (IP67)",
        "slug": "radio-baofeng-uv-9r-plus",
        "sku": "BF-UV9R-PLUS",
        "category": "radios-comunicacoes",
        "cost": 33.0,
        "order": 24,
        "short_description": "10 W, 128 canais e corpo IP67 para chuva, poeira e uso exterior. Bateria de 4800 mAh.",
        "description": (
            "## O que inclui\n\n"
            "- Rádio Baofeng UV-9R Plus\n"
            "- Bateria de lítio 4800 mAh\n"
            "- Carregador de dock\n"
            "- Antena, presilha de cinto e auscultador com PTT\n\n"
            "## Características\n\n"
            "- Dupla banda: 144–146 MHz e 430–440 MHz\n"
            "- 10 W de potência de transmissão\n"
            "- Corpo estanque IP67 (chuva, poeira e imersão breve)\n"
            "- 128 canais e programação por cabo (não incluído)\n\n"
            "Feito para quem trabalha ao ar livre: floresta, costa, obras e proteção civil.\n\n"
            f"{PRAZO}\n\n{NOTA_LEGAL_RADIOS}"
        ),
        "tags": ["baofeng", "uv-9r-plus", "ip67", "à-prova-de-água", "walkie-talkie", "10w"],
        "attributes": [
            {"label": "Bandas", "value": "144–146 MHz / 430–440 MHz"},
            {"label": "Potência", "value": "10 W"},
            {"label": "Estanquidade", "value": "IP67"},
            {"label": "Bateria", "value": "4800 mAh"},
        ],
        "weight_kg": 0.6,
        "length_cm": 21.0,
        "width_cm": 13.0,
        "height_cm": 9.0,
        "internal_notes": "Origem: AliExpress (dropshipping UE). Foto e ficha seguem o anúncio 1005005057183061 («UV9R Plus Baofeng Walkie Talkie IP67 ... 4800mah»). Custo estimado 33,00 €; preço a 2,5× o custo. Confirmar oferta do fornecedor antes de cada reposição.",
    },
    {
        "name": "Rádio Baofeng GT-5R — 144/430 MHz",
        "slug": "radio-baofeng-gt-5r",
        "sku": "BF-GT5R",
        "category": "radios-comunicacoes",
        "cost": 28.0,
        "order": 25,
        "short_description": "A variante do UV-5R com transmissão limitada às bandas amadoras de 144–146 e 430–440 MHz.",
        "description": (
            "## O que inclui\n\n"
            "- Rádio Baofeng GT-5R\n"
            "- Bateria de lítio 1800 mAh\n"
            "- Carregador de dock\n"
            "- Antena, presilha de cinto e auscultador com PTT\n\n"
            "## Características\n\n"
            "- Transmissão limitada a 144–146 MHz e 430–440 MHz\n"
            "- 5 W de potência e 128 canais\n"
            "- Receção alargada, com teclado numérico e ecrã LCD iluminado\n"
            "- Programação por cabo (não incluído)\n\n"
            "É a versão do UV-5R que não transmite fora das bandas amadoras — a escolha "
            "para radioamadores com licença que querem um equipamento de bolso.\n\n"
            f"{PRAZO}\n\n{NOTA_LEGAL_RADIOS}"
        ),
        "tags": ["baofeng", "gt-5r", "radioamador", "144-430", "walkie-talkie"],
        "attributes": [
            {"label": "Bandas", "value": "144–146 MHz / 430–440 MHz"},
            {"label": "Potência", "value": "5 W"},
            {"label": "Canais", "value": "128"},
            {"label": "Bateria", "value": "1800 mAh"},
        ],
        "weight_kg": 0.45,
        "length_cm": 20.0,
        "width_cm": 12.0,
        "height_cm": 8.0,
        "internal_notes": "Origem: AliExpress (dropshipping UE). Custo estimado 28,00 €; preço a 2,5× o custo. Confirmar oferta do fornecedor antes de cada reposição.",
    },
    {
        "name": "Kit de sobrevivência 72 horas — mochila completa",
        "slug": "kit-sobrevivencia-72h",
        "sku": "KIT-72H",
        "category": "kits-sobrevivencia",
        "cost": 38.0,
        "featured": True,
        "order": 26,
        "short_description": "Mochila de 40 L com abrigo, água, alimento, iluminação, primeiros socorros e ferramentas para 72 horas de autonomia.",
        "description": (
            "## O que inclui\n\n"
            "- Mochila de 40 L com vários compartimentos\n"
            "- Abrigo de emergência, manta térmica e saco-cama fino\n"
            "- Filtro de água portátil e garrafa dobrável\n"
            "- Rações de emergência e barra de sobrevivência\n"
            "- Lanterna de cabeça, apito e velas\n"
            "- Kit de primeiros socorros compacto\n"
            "- Corda de paracord, canivete e kit de fogo\n"
            "- Rádio de manivela com lanterna e carregador USB\n\n"
            "## Para quem é\n\n"
            "Preparação para falhas de eletricidade, cheias, sismos ou saída rápida de casa. "
            "Dá 72 horas de autonomia a uma pessoa, o intervalo típico até os meios de "
            "emergência chegarem.\n\n"
            f"{PRAZO}"
        ),
        "tags": ["kit", "sobrevivência", "72h", "mochila", "emergência", "preparação"],
        "attributes": [
            {"label": "Autonomia", "value": "72 horas (1 pessoa)"},
            {"label": "Mochila", "value": "40 L"},
            {"label": "Peças", "value": "Mais de 60"},
            {"label": "Peso", "value": "Cerca de 6,5 kg"},
        ],
        "weight_kg": 6.5,
        "length_cm": 45.0,
        "width_cm": 30.0,
        "height_cm": 20.0,
        "internal_notes": "Origem: Temu / AliExpress (dropshipping UE). Custo estimado 38,00 €; preço a 2,5× o custo. Confirmar composição do kit na oferta antes de cada reposição.",
    },
    {
        "name": "Kit de primeiros socorros — 120 peças",
        "slug": "kit-primeiros-socorros-120-pecas",
        "sku": "KIT-PS-120",
        "category": "kits-sobrevivencia",
        "cost": 11.0,
        "order": 27,
        "short_description": "Bolsa MOLLE com 120 peças: pensos, compressas, ligaduras, tesoura, ligadura triangular e compressa de gelo.",
        "description": (
            "## O que inclui\n\n"
            "- Bolsa MOLLE com fecho e presilhas (cinto ou mochila)\n"
            "- Pensos rápidos de vários tamanhos e pensos estéreis\n"
            "- Compressas, adesivo médico e toalhetes antissépticos\n"
            "- Ligaduras elásticas e ligadura triangular\n"
            "- Tesoura, pinça e luvas descartáveis\n"
            "- Compressa de gelo instantânea\n\n"
            "Um kit de uso geral para tratar cortes e queimaduras ligeiras em casa, no "
            "trabalho ou na estrada. Não substitui formação em primeiros socorros.\n\n"
            f"{PRAZO}"
        ),
        "tags": ["kit", "primeiros-socorros", "emergência", "farmácia", "120-peças"],
        "attributes": [
            {"label": "Peças", "value": "120"},
            {"label": "Bolsa", "value": "MOLLE com presilhas"},
            {"label": "Uso", "value": "Casa, carro ou mochila"},
        ],
        "weight_kg": 0.8,
        "length_cm": 25.0,
        "width_cm": 18.0,
        "height_cm": 10.0,
        "internal_notes": "Origem: AliExpress (dropshipping UE). Foto e ficha seguem o anúncio 1005013396779633 («Kit de primeiros socorros ... 120 peças ... Molle»). Custo estimado 11,00 €; preço a 2,5× o custo. Confirmar validade dos consumíveis na oferta.",
    },
    {
        "name": "Kit de purificação de água — palha filtrante 0,01 µm",
        "slug": "kit-purificacao-agua",
        "sku": "KIT-AGUA",
        "category": "kits-sobrevivencia",
        "cost": 13.0,
        "order": 28,
        "short_description": "Palha filtrante de 0,01 µm, até 1 000 litros: água potável direta de rios, lagos e fontes.",
        "description": (
            "## O que inclui\n\n"
            "- Filtro de palha com membrana de 0,01 µm (até 1 000 litros)\n"
            "- Tampa protetora e cordão de transporte\n"
            "- Instruções de uso\n\n"
            "## Como usar\n\n"
            "1. Mergulhe a ponta na água corrente ou parada, evitando água com químicos.\n"
            "2. Beba diretamente pela palha, sem esforço.\n"
            "3. Sopre para o filtro ficar seco e guarde-o sem gelo entre utilizações.\n\n"
            "Para caminhadas, campismo, van life e kits de emergência.\n\n"
            f"{PRAZO}"
        ),
        "tags": ["kit", "água", "filtro", "purificação", "campismo", "sobrevivência"],
        "attributes": [
            {"label": "Filtração", "value": "0,01 µm"},
            {"label": "Capacidade", "value": "1 000 litros"},
            {"label": "Formato", "value": "Palha portátil"},
        ],
        "weight_kg": 0.4,
        "length_cm": 20.0,
        "width_cm": 12.0,
        "height_cm": 6.0,
        "internal_notes": "Origem: AliExpress (dropshipping UE). Foto e ficha seguem o anúncio 1005006138375217 («Filterwell Green Mini Viagem Filtro De Água Palha»). Custo estimado 13,00 €; preço a 2,5× o custo. Confirmar certificação do filtro na oferta.",
    },
    {
        "name": "Kit de fogo e bushcraft — pederneira e acendalha",
        "slug": "kit-fogo-bushcraft",
        "sku": "KIT-FOGO",
        "category": "kits-sobrevivencia",
        "cost": 9.0,
        "order": 29,
        "short_description": "Pederneira de ferrocerium com raspador, cordão e acendalha: fogo com chuva e vento.",
        "description": (
            "## O que inclui\n\n"
            "- Pederneira de ferrocerium com raspador\n"
            "- Acendalha seca\n"
            "- Cordão de transporte e argola\n\n"
            "Faz faísca mesmo molhada e dura milhares de utilizações — não depende de gás "
            "nem de combustível. Cabe no bolso do casaco ou na lateral da mochila.\n\n"
            f"{PRAZO}"
        ),
        "tags": ["kit", "fogo", "bushcraft", "pederneira", "sobrevivência", "campismo"],
        "attributes": [
            {"label": "Inclui", "value": "Pederneira, raspador e acendalha"},
            {"label": "Uso", "value": "Campismo e emergência"},
        ],
        "weight_kg": 0.3,
        "length_cm": 15.0,
        "width_cm": 10.0,
        "height_cm": 5.0,
        "internal_notes": "Origem: AliExpress (dropshipping UE). Foto e ficha seguem o anúncio 1005013457663726 («Kit de acendimento de fogo de emergência ... com pavio»). Custo estimado 9,00 €; preço a 2,5× o custo. Atenção ao transporte aéreo.",
    },
    {
        "name": "Kit de ferramentas multifunções — 14 em 1",
        "slug": "kit-ferramentas-multifuncoes",
        "sku": "KIT-FERR-14",
        "category": "kits-sobrevivencia",
        "cost": 14.0,
        "order": 30,
        "short_description": "Alicate multifunções 14 em 1 com faca, serra, chaves e bits, em bolsa de nylon.",
        "description": (
            "## O que inclui\n\n"
            "- Alicate multifunções 14 em 1\n"
            "- Faca, serra e lâmina de corte\n"
            "- Chaves de fendas e bits de parafusos\n"
            "- Abre-latas, abre-garrafas e saca-rolhas\n"
            "- Bolsa de nylon com presilha\n\n"
            "Uma só ferramenta resolve a maior parte das reparações de campo — e é o que "
            "costuma faltar num kit de emergência.\n\n"
            f"{PRAZO}"
        ),
        "tags": ["kit", "ferramentas", "multifunções", "alicate", "campismo", "reparação"],
        "attributes": [
            {"label": "Funções", "value": "14"},
            {"label": "Material", "value": "Aço inoxidável"},
            {"label": "Bolsa", "value": "Nylon com presilha"},
            {"label": "Peso", "value": "Cerca de 350 g"},
        ],
        "weight_kg": 0.35,
        "length_cm": 15.0,
        "width_cm": 10.0,
        "height_cm": 4.0,
        "internal_notes": "Origem: Temu / AliExpress (dropshipping UE). Custo estimado 14,00 €; preço a 2,5× o custo. Confirmar qualidade do aço na oferta.",
    },
    {
        "name": "Kit de emergência automóvel — cabo, compressor e sinalização",
        "slug": "kit-emergencia-automovel",
        "sku": "KIT-AUTO",
        "category": "kits-sobrevivencia",
        "cost": 22.0,
        "order": 31,
        "short_description": "Cabo de bateria de 400 A, compressor de 12 V, triângulo, colete refletor e lanterna para o porta-bagagens.",
        "description": (
            "## O que inclui\n\n"
            "- Cabos de bateria de 400 A (2,5 m)\n"
            "- Compressor de ar de 12 V com manómetro\n"
            "- Triângulo de sinalização e colete refletor\n"
            "- Lanterna LED com íman\n"
            "- Kit de fusíveis e luvas de trabalho\n"
            "- Bolsa de arrumação\n\n"
            "## Para quem é\n\n"
            "Quem faz muitos quilómetros, viaja com crianças ou circula de noite. Inclui o "
            "que a lei portuguesa exige em caso de imobilização e o que resolve os dois "
            "problemas mais comuns: bateria e pneu.\n\n"
            f"{PRAZO}"
        ),
        "tags": ["kit", "automóvel", "emergência", "carro", "cabo-bateria", "compressor"],
        "attributes": [
            {"label": "Cabos", "value": "400 A, 2,5 m"},
            {"label": "Compressor", "value": "12 V com manómetro"},
            {"label": "Sinalização", "value": "Triângulo e colete"},
            {"label": "Peso", "value": "Cerca de 4,2 kg"},
        ],
        "weight_kg": 4.2,
        "length_cm": 40.0,
        "width_cm": 28.0,
        "height_cm": 18.0,
        "internal_notes": "Origem: Temu / AliExpress (dropshipping UE). Custo estimado 22,00 €; preço a 2,5× o custo. Confirmar homologação do triângulo e do colete.",
    },
]


def preco(custo: float) -> float:
    """Preço de venda: o custo estimado com a margem do multiplicador."""
    return round(custo * MULTIPLICADOR + 1e-9, 2)


def _euros(valor: float) -> str:
    return f"{valor:.2f} €".replace(".", ",")


def _categorias(atualizar: bool) -> Dict[str, str]:
    """Garante as categorias e devolve `slug → id`."""
    ids: Dict[str, str] = {}
    for categoria in CATEGORIAS:
        existente = store.category_by_slug(categoria["slug"])
        if existente and not atualizar:
            print(f"  categoria: {categoria['name']} — já existia")
            ids[categoria["slug"]] = existente["id"]
            continue
        payload = {**categoria, "status": "publicado"}
        if existente:
            payload["id"] = existente["id"]
        guardada = store.save_item("categories", payload, AUTOR)
        ids[categoria["slug"]] = guardada["id"]
        print(f"  categoria: {categoria['name']} — {'atualizada' if existente else 'criada'}")
    return ids


def _produtos(categorias: Dict[str, str], atualizar: bool) -> Dict[str, int]:
    """Cria (ou atualiza) os produtos e devolve a contagem por resultado."""
    resultado = {"criados": 0, "atualizados": 0, "ignorados": 0}
    for produto in PRODUTOS:
        atual = store.product_by_slug(produto["slug"], published_only=False)
        if atual and not atualizar:
            resultado["ignorados"] += 1
            print(f"  produto: {produto['name']} — já existia")
            continue

        payload: Dict[str, Any] = {
            "name": produto["name"],
            "slug": produto["slug"],
            "sku": produto["sku"],
            "type": "fisico",
            "status": "publicado",
            "featured": produto.get("featured", False),
            "order": produto["order"],
            "short_description": produto["short_description"],
            "description": produto["description"],
            "price": preco(produto["cost"]),
            "cost": produto["cost"],
            "tax_rate": 23.0,
            "stock": 0,
            "stock_min": 0,
            "track_stock": True,
            "allow_backorder": True,
            "unit": "un",
            "category_ids": [categorias[produto["category"]]],
            "tags": produto["tags"],
            "attributes": produto["attributes"],
            "weight_kg": produto["weight_kg"],
            "length_cm": produto["length_cm"],
            "width_cm": produto["width_cm"],
            "height_cm": produto["height_cm"],
            "internal_notes": produto["internal_notes"],
        }
        if atual:
            payload["id"] = atual["id"]
        guardado = store.save_item("products", payload, AUTOR)
        chave = "atualizados" if atual else "criados"
        resultado[chave] += 1
        print(
            f"  produto: {guardado['name']} — {_euros(guardado['price'])} "
            f"(custo {_euros(guardado['cost'])}) — {'atualizado' if atual else 'criado'}"
        )
    return resultado


def _imagens() -> None:
    """Liga a cada produto a imagem de marca que viaja com o código."""
    resultado = store.instalar_imagens_de_produto(AUTOR)
    if not resultado["instalados"]:
        print("  imagens: já estavam todas ligadas")
        return
    print(f"  imagens: ligadas a {resultado['instalados']} produto(s)")


def main(argv: List[str]) -> int:
    atualizar = "--atualizar" in argv
    if not atualizar:
        print("modo: criar só o que faltar (use --atualizar para repor os campos)")

    categorias = _categorias(atualizar)
    resultado = _produtos(categorias, atualizar)
    _imagens()

    publicados = len(store.public_products(limit=500))
    print(
        f"loja: {resultado['criados']} produto(s) criado(s), "
        f"{resultado['atualizados']} atualizado(s), {resultado['ignorados']} já existia(m) "
        f"— {publicados} publicados na vitrine"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
