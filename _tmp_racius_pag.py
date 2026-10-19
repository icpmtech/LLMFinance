import io, re
h = io.open(r'C:\LLMFinance\_tmp_racius_porto.html', encoding='utf-8').read()
i = h.find('results__found')
print(h[i-200:i+300].replace('\n', ' '))
print('\n--- paginacao ---')
for m in re.finditer(r'<a[^>]*href="([^"]*(?:page|pagina)[^"]*)"[^>]*>', h):
    print(m.group(0)[:200])
print('\n--- links resultados ---')
print(len(re.findall(r'results__col-link', h)))
print(re.findall(r'href="(/[^"]+/)" class="results__col-link"', h)[:3])
