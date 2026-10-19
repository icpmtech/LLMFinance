import io, re
h = io.open(r'C:\LLMFinance\_tmp_racius_porto.html', encoding='utf-8').read()
print('concelho ocorrencias:', h.lower().count('concelho'))
for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>([^<]{0,60})</a>', h):
    if 'concelho' in m.group(1).lower() or 'concelho' in m.group(2).lower():
        print(m.group(1), '|', m.group(2).strip())
