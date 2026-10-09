# Análise de negócio do IQ OS

Esta pasta é **gerada**: não se edita à mão. Contém a análise de negócio da solução
(produto, mercado, impacto) construída a partir de dados recolhidos da própria
plataforma em execução — não de estimativas.

## Conteúdo

| Ficheiro | O que é |
| --- | --- |
| `IQOS_Analise_Negocio.pptx` | Apresentação com 18 diapositivos (produto, mercado, modelo de negócio, forças, fraquezas, scorecard, plano, impacto). |
| `relatorio_negocio.md` | A mesma leitura em texto, com as fontes de cada número. |
| `analise_iqos.json` | Todos os valores recolhidos + métricas derivadas + scorecard. É a fonte do PowerPoint. |
| `graficos/*.png` | Gráficos (documentos por índice, países, funil de cobertura, scorecard, cenários de receita). |
| `ecras/*.png` | 16 ecrãs reais da aplicação, capturados por Playwright com sessão de serviço. |
| `_slides/*.png` | Os 18 diapositivos exportados em imagem (só para revisão rápida do layout). |

## Como regenerar

```powershell
cd c:\LLMFinance\finance-llm

# 1. Recolher os dados da plataforma (tem de correr dentro do container: precisa
#    de Elasticsearch e do índice de chaves para abrir a sessão de serviço)
docker exec finance-llm-backend python /app/logs/_analise_negocio_iqos.py --base http://127.0.0.1:8000

# 2. Capturar os ecrãs da aplicação (precisa do frontend a correr)
c:\LLMFinance\.venv\Scripts\python.exe logs\_capturar_ecras_iqos.py --base http://127.0.0.1:4180

# 3. Gerar o PowerPoint
c:\LLMFinance\.venv\Scripts\python.exe logs\_gerar_ppt_iqos.py

# 4. (opcional) exportar os diapositivos em PNG, para revisão do layout
powershell -NoProfile -ExecutionPolicy Bypass -File logs\_exportar_ppt_png.ps1
```

## O que os números **não** dizem

A plataforma ainda não tem telemetria de produto. Não há contagem de utilizadores
ativos, retenção, conversão nem ARPU — por isso o relatório e a apresentação
**não apresentam nenhum número de clientes ou receita real**. As únicas partes
assumidas são o TAM/SAM/SOM e o preço de referência de 49 €/mês, sempre marcadas
como pressupostos a confirmar.

Os endpoints que não responderam (por exigirem administração ou ainda não
existirem) ficam registados em `metricas.nao_medido`, dentro do JSON.

## Notas de execução (2026-10-09)

- A captura de ecrãs precisa de **sessão**: um contexto novo do Playwright não herda
a do browser; o script cria uma sessão de serviço no container e injecta o token em
`localStorage['finance-llm-token']` antes de navegar.
- O painel de consentimento do iubenda vive num **iframe** e tapa o centro do ecrã:
o script aceita-o (`frame_locator`) e injecta CSS de reserva antes de cada captura.
- As janelas da aplicação são retomadas de `localStorage['finance-llm-windows:v1']`;
limpa-se esse layout por rota para cada ecrã mostrar **uma** janela.
- Alguns ecrãs registaram **500** na consola (o módulo de recolha/scraper é o mais
visível) e `/scraper/stats` chega a exceder o tempo limite de resposta — vale a pena
investigar, mas não impede a análise.
