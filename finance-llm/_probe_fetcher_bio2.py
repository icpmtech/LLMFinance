from scrapling.fetchers import Fetcher
import sys
bid = sys.argv[1] if len(sys.argv) > 1 else '7489'
url = f'https://www.parlamento.pt/DeputadoGP/Paginas/Biografia.aspx?BID={bid}'
r = Fetcher.get(url, stealthy_headers=True, timeout=30, http_version=2)
print('status', getattr(r, 'status_code', None))
print('len text', len(r.text))
print('len body', len(getattr(r, 'body', b'')))
print('len get_all_text', len(r.get_all_text()))
for kind in ['strict','relaxed','col-xs-12']:
    if kind=='strict':
        nodes = r.xpath("//div[contains(@class,'col-xs-12')][div[@class='TextoRegular-Titulo']][div[contains(@class,'TitulosBio')]]")
    elif kind=='relaxed':
        nodes = r.xpath("//div[contains(@class,'col-xs-12')][.//div[@class='TextoRegular-Titulo']][.//div[contains(@class,'TitulosBio')]]")
    else:
        nodes = r.css('div.col-xs-12')
    print(f'\n{kind} nodes', len(nodes))
    for i, n in enumerate(nodes):
        txt = n.get_all_text()
        cls = (getattr(n, 'attributes', {}) or {}).get('class','')
        print(f'  {i} class={cls!r} len={len(txt)}', repr(txt[:250].replace('\n', ' ')))
