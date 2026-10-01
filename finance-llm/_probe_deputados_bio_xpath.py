import sys, json
sys.path.insert(0, '.')
from api.scraper_templates import build_source
from api.scraper_service import _open_session, _session_fetch

source = build_source('parlamento-deputados')
opts = source['options']
opts['timeout'] = 30
opts['http_version'] = 2
with _open_session('http', opts) as session:
    page = _session_fetch(session, 'http', 'https://www.parlamento.pt/DeputadoGP/Paginas/Biografia.aspx?BID=7489', opts)
    print('url', page.url)
    print('len html', len(page.text))
    title = page.css('title::text')
    print('title', title.get() if hasattr(title, 'get') else title)
    nodes = page.xpath("//div[contains(@class, 'col-xs-12')][div[@class='TextoRegular-Titulo']][div[contains(@class, 'TitulosBio')]]")
    print('nodes count', len(nodes))
    if nodes:
        txt = nodes[0].get_all_text()
        print('text len', len(txt))
        print(txt[:300].replace('\n', ' '))
    else:
        # fallback: mostrar classes encontradas
        print('FALLBACK col-xs-12 count', len(page.css('.col-xs-12')))
        print('FALLBACK TitulosBio count', len(page.css('.TitulosBio')))
        print('FALLBACK TextoRegular-Titulo count', len(page.css('.TextoRegular-Titulo')))
