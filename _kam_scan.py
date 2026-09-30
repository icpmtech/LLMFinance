import re, sys, io

path = sys.argv[1]
src = io.open(path, encoding="utf-8", errors="replace").read()
print("len:", len(src))

pat = re.compile(r"""["'`]([^"'`\s]{0,80}?/api/[^"'`\s]{0,80})["'`]""")
cands = sorted(set(pat.findall(src)))
print("api refs:", len(cands))
for c in cands[:120]:
    print("  ", c)

pat2 = re.compile(r"""["'`](/(?:service|billing|auth|user|account)[A-Za-z0-9_\-/]*)["'`]""")
c2 = sorted(set(pat2.findall(src)))
print("service-ish:", len(c2))
for c in c2[:120]:
    print("  ", c)
