import io
h = io.open(r'C:\LLMFinance\_tmp_racius_detail.html', encoding='utf-8').read()
i = h.rfind('> Morada<')
print(i)
print(h[max(0, i-700):i+900].replace('\n', ' '))
