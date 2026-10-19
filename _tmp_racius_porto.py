import io, re
h = io.open(r'C:\LLMFinance\_tmp_racius_porto.html', encoding='utf-8').read()
for pat in [r'([\d\.\s]+)\s*(resultados|empresas)', r'p[áa]gina\s*(\d+)\s*de\s*(\d+)', r'page=(\d+)', r'max_pages|last']:
    ms = re.findall(pat, h, flags=re.I)
    print(pat, '->', ms[:10])
i = h.find('results__col-link')
print(h[i-600:i+400].replace('\n', ' '))
