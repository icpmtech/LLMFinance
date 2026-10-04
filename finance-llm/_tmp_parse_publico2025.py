import httpx, re, json
url='https://www.publico.pt/2025/06/02/infografia/sao-deputados-863'
r=httpx.get(url, headers={'User-Agent':'Mozilla/5.0'}, timeout=45, follow_redirects=True)
text=r.text
for arr_name in ['deputadosBE','deputadosPS','deputadosChega','deputadosIL','deputadosLivre','deputadosPAN','deputadosPCP','deputadosPSD','deputadosCDS','deputadosJPP']:
    pat = r'var\s+'+arr_name+r'\s*=\s*(\[.*?\]);'
    m=re.search(pat, text, re.S)
    if not m:
        print(arr_name, 'not found')
        continue
    raw=m.group(1)
    raw2=raw.replace("'", '"')
    raw2=re.sub(r',\s*\]', ']', raw2)
    try:
        data=json.loads(raw2)
        print(arr_name, len(data), data[0])
    except Exception as e:
        print(arr_name, 'error', e, repr(raw[:80]))
