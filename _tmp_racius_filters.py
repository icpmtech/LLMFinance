import io, re
h = io.open(r'C:\LLMFinance\_tmp_racius_list.html', encoding='utf-8').read()
i = h.find('id="filters"')
seg = h[i:i + 12000]
for m in re.finditer(r'<(input|select|option|button|a)\b[^>]*>', seg):
    print(m.group(0)[:300])

