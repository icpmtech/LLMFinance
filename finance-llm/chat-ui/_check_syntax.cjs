// Localiza o erro de sintaxe: diz até onde o parser conseguiu ler e onde falhou.
const fs = require("fs");
const ts = require("typescript");

const file = process.argv[2];
const text = fs.readFileSync(file, "utf8");
const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

const at = (pos) => {
  const lc = sf.getLineAndCharacterOfPosition(Math.min(pos, text.length));
  return `${lc.line + 1}:${lc.character + 1}`;
};

console.log("--- diagnósticos ---");
for (const d of sf.parseDiagnostics) {
  console.log(`${at(d.start)} (start ${d.start}):`, ts.flattenDiagnosticMessageText(d.messageText, " "));
}

console.log("--- statements topo de ficheiro ---");
for (const st of sf.statements) {
  const name = st.name && st.name.text ? " " + st.name.text : "";
  console.log(`${ts.SyntaxKind[st.kind]}${name}: ${at(st.getStart(sf))} → ${at(st.getEnd())}`);
}

// Procura o primeiro ponto em que a estrutura deixa de ser coerente: fim do último
// statement completo vs. fim do ficheiro.
const last = sf.statements[sf.statements.length - 1];
console.log("--- ficheiro ---");
console.log("linhas:", text.split(/\r?\n/).length, "| tamanho:", text.length);
console.log("fim do último statement:", at(last ? last.getEnd() : 0));
