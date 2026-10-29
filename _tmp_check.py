import io, os
t = io.open(os.path.join(os.environ["TEMP"], "cvd_new.html"), encoding="utf-8").read()
for k in ["média do país", "mediana do país", "Despesa/hab.", 'data-k="dp"']:
    print(repr(k), "->", t.count(k))
i = t.find("<thead>")
print(t[i:i + 800])
