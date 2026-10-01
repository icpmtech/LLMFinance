from scrapling.fetchers import Fetcher

r = Fetcher.get('https://www.parlamento.pt/DeputadoGP/Paginas/Biografia.aspx?BID=7489', stealthy_headers=True, timeout=30, http_version=2)
print('len text', len(r.text))
print('len get_all_text', len(r.get_all_text()))
print('col-xs-12 count', len(r.css('.col-xs-12')))
print('TitulosBio count', len(r.css('.TitulosBio')))
print('TextoRegular-Titulo count', len(r.css('.TextoRegular-Titulo')))
nodes = r.xpath("//div[contains(@class,'col-xs-12')][div[@class='TextoRegular-Titulo']][div[contains(@class,'TitulosBio')]]")
print('strict xpath nodes count', len(nodes))
# relax condition
nodes2 = r.xpath("//div[contains(@class,'col-xs-12')][.//div[@class='TextoRegular-Titulo']][.//div[contains(@class,'TitulosBio')]]")
print('relaxed xpath nodes count', len(nodes2))
for i, n in enumerate(nodes2):
    print(f'--- node {i} len {len(n.get_all_text())}', repr(n.get_all_text()[:500].replace('\n', ' ')))
