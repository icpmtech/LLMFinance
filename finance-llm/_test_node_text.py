from scrapling.fetchers import Fetcher

F = Fetcher(impersonate='chrome')
page = F.get('https://www.iberinform.pt/empresa/21288469/jose-and-emilio-l-barahona-lda')
node = page.css('section.section-company-data')
print('node type', type(node))
print('attrs', [a for a in dir(node) if not a.startswith('_')][:40])
print('text attr', hasattr(node, 'text'))
print('get_all_text callable', callable(getattr(node, 'get_all_text', None)))
if callable(getattr(node, 'get_all_text', None)):
    print('len get_all_text', len(node.get_all_text()))
print('text attr value len', len(getattr(node, 'text', '')))
print('getall len', len(' '.join(node.getall())))
print('first len', len(node.first.text) if hasattr(node, 'first') and node.first else 'N/A')
try:
    print('first text', node.first.text[:80])
except Exception as e:
    print('first text error', e)
