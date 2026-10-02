/**
 * Página **Documentos** (rota `/documentos`).
 *
 * Mostra os documentos de referência que vivem na pasta `data/docs` do backend
 * e a **versão markdown** de cada um. Tem dois separadores:
 *
 * 1. **Ficheiros** — a lista da pasta (nome, tipo, tamanho, data) e, ao abrir,
 *    o documento em markdown (ou o aviso de que só existe o original).
 * 2. **CAE-Rev.4** — a Classificação Portuguesa das Atividades Económicas
 *    (Revisão 4, INE) convertida do PDF para markdown: navegação pelas secções
 *    e pesquisa por código/designação.
 *
 * O markdown vem do endpoint `/docs/markdown/{nome}`; quando não existe um `.md`
 * irmão, o backend converte ficheiros de texto a pedido.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  Download,
  ExternalLink,
  FileCode2,
  FileText,
  FolderOpen,
  Hash,
  Layers,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui";
import { MarkdownView } from "../components/office/MarkdownView";
import {
  docFileUrl,
  getDocMarkdown,
  listDocs,
  type DocsItem,
  type DocsMarkdown,
} from "../docsApi";

/* -------------------------------------------------------------- CAE (parser) */

type CaeSection = { letter: string; title: string; body: string; divisions: number; intro?: boolean };
type CaeEntry = {
  code: string;
  name: string;
  level: string;
  section: string;
  path: string;
};

const RE_SECCAO = /^## Secção ([A-Z]) — (.*)$/;
const RE_DIVISAO = /^### Divisão (\d{2}) — (.*)$/;
const RE_GRUPO = /^#### Grupo (\d{3}) — (.*)$/;
const RE_CLASSE_SUB = /^##### Classe (\d{4}) \(subclasse (\d{5})\) — (.*)$/;
const RE_CLASSE = /^##### Classe (\d{4}) — (.*)$/;
const RE_SUBCLASSE = /^- \*\*(\d{5})\*\* — (.*)$/;

/**
 * Lê o markdown do CAE numa lista de secções (para navegar) e numa lista de
 * entradas (para pesquisar), mantendo o caminho hierárquico de cada código.
 */
function parseCae(markdown: string) {
  const sections: CaeSection[] = [];
  const entries: CaeEntry[] = [];
  const intro: string[] = [];
  let atual: CaeSection | null = null;
  let divisao = "";
  let grupo = "";
  let seccaoLetra = "";

  for (const linha of markdown.split("\n")) {
    let m: RegExpMatchArray | null;
    if ((m = linha.match(RE_SECCAO))) {
      atual = { letter: m[1], title: m[2].trim(), body: linha, divisions: 0 };
      sections.push(atual);
      seccaoLetra = m[1];
      divisao = "";
      grupo = "";
      entries.push({ code: m[1], name: m[2].trim(), level: "Secção", section: m[1], path: "" });
      continue;
    }
    if (!atual) {
      intro.push(linha);
      continue;
    }
    atual.body += `\n${linha}`;
    if ((m = linha.match(RE_DIVISAO))) {
      divisao = m[1];
      grupo = "";
      atual.divisions += 1;
      entries.push({
        code: m[1],
        name: m[2].trim(),
        level: "Divisão",
        section: seccaoLetra,
        path: `Secção ${seccaoLetra}`,
      });
      continue;
    }
    if ((m = linha.match(RE_GRUPO))) {
      grupo = m[1];
      entries.push({
        code: m[1],
        name: m[2].trim(),
        level: "Grupo",
        section: seccaoLetra,
        path: `Divisão ${divisao}`,
      });
      continue;
    }
    if ((m = linha.match(RE_CLASSE_SUB))) {
      entries.push({
        code: m[1],
        name: m[3].trim(),
        level: "Classe",
        section: seccaoLetra,
        path: `Divisão ${divisao} › Grupo ${grupo}`,
      });
      entries.push({
        code: m[2],
        name: m[3].trim(),
        level: "Subclasse",
        section: seccaoLetra,
        path: `Divisão ${divisao} › Grupo ${grupo} › Classe ${m[1]}`,
      });
      continue;
    }
    if ((m = linha.match(RE_CLASSE))) {
      entries.push({
        code: m[1],
        name: m[2].trim(),
        level: "Classe",
        section: seccaoLetra,
        path: `Divisão ${divisao} › Grupo ${grupo}`,
      });
      continue;
    }
    if ((m = linha.match(RE_SUBCLASSE))) {
      entries.push({
        code: m[1],
        name: m[2].trim(),
        level: "Subclasse",
        section: seccaoLetra,
        path: `Divisão ${divisao} › Grupo ${grupo} › Classe ${m[1].slice(0, 4)}`,
      });
    }
  }

  const counts = entries.reduce(
    (acc, entry) => {
      acc[entry.level] = (acc[entry.level] ?? 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );
  const textoIntro = intro.join("\n").trim();
  if (textoIntro) {
    // A introdução do quadro (antes da 1.ª secção) entra como primeira entrada
    // do índice, para não se perder o enquadramento da classificação.
    sections.unshift({ letter: "§", title: "Introdução", body: textoIntro, divisions: 0, intro: true });
  }
  return { sections, entries, counts };
}

/* ----------------------------------------------------------------- helpers */

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const unidades = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), unidades.length - 1);
  const valor = bytes / 1024 ** i;
  return `${valor.toFixed(i === 0 ? 0 : valor >= 10 ? 0 : 1)} ${unidades[i]}`;
}

function formatDate(iso: string): string {
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return "—";
  return data.toLocaleString("pt-PT", { dateStyle: "medium", timeStyle: "short" });
}

function plural(n: number, singular: string, pluralForm?: string): string {
  return `${n} ${n === 1 ? singular : pluralForm ?? `${singular}s`}`;
}

function downloadText(name: string, texto: string) {
  const blob = new Blob([texto], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/* -------------------------------------------------------------------- página */

export default function DocsPage() {
  const [tab, setTab] = useState<"ficheiros" | "cae">("ficheiros");
  const [docs, setDocs] = useState<DocsItem[]>([]);
  const [pasta, setPasta] = useState("");
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [aberto, setAberto] = useState<DocsMarkdown | null>(null);
  const [carregandoDoc, setCarregandoDoc] = useState(false);
  const [erroDoc, setErroDoc] = useState<string | null>(null);
  const [docAtual, setDocAtual] = useState<string | null>(null);

  const [caeMd, setCaeMd] = useState<string | null>(null);
  const [erroCae, setErroCae] = useState<string | null>(null);
  const [seccaoAtiva, setSeccaoAtiva] = useState(0);
  const [pesquisa, setPesquisa] = useState("");

  const carregarLista = useCallback(async () => {
    setLoading(true);
    setErro(null);
    try {
      const lista = await listDocs();
      setDocs(lista.items);
      setPasta(lista.folder);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void carregarLista();
  }, [carregarLista]);

  const abrirDocumento = useCallback(async (nome: string) => {
    setDocAtual(nome);
    setCarregandoDoc(true);
    setErroDoc(null);
    setAberto(null);
    try {
      setAberto(await getDocMarkdown(nome));
    } catch (err) {
      setErroDoc(err instanceof Error ? err.message : String(err));
    } finally {
      setCarregandoDoc(false);
    }
  }, []);

  // O documento original do CAE é o PDF (o `.md` é a versão gerada a partir dele).
  const caeDoc = useMemo(() => {
    const candidatos = docs.filter((doc) => /cae/i.test(doc.name));
    return candidatos.find((doc) => doc.extension !== "md") ?? candidatos[0];
  }, [docs]);

  useEffect(() => {
    if (!caeDoc) return;
    let activo = true;
    setErroCae(null);
    getDocMarkdown(caeDoc.name)
      .then((payload) => {
        if (activo) setCaeMd(payload.markdown);
      })
      .catch((err: unknown) => {
        if (activo) setErroCae(err instanceof Error ? err.message : String(err));
      });
    return () => {
      activo = false;
    };
  }, [caeDoc]);

  const cae = useMemo(() => (caeMd ? parseCae(caeMd) : null), [caeMd]);

  const resultados = useMemo(() => {
    const termo = pesquisa.trim().toLowerCase();
    if (!cae || termo.length < 2) return [];
    return cae.entries
      .filter(
        (entry) =>
          entry.code.toLowerCase().startsWith(termo) ||
          entry.name.toLowerCase().includes(termo) ||
          entry.path.toLowerCase().includes(termo),
      )
      .slice(0, 400);
  }, [cae, pesquisa]);

  const seccao = cae?.sections[seccaoAtiva] ?? null;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="border-b px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 text-white shadow-lg shadow-orange-500/25">
              <BookOpen size={20} />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Documentos</h1>
              <p className="text-sm text-muted-foreground">
                Documentos de referência de <span className="font-mono text-xs">data/docs</span> e a classificação CAE em markdown
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {pasta && (
              <span className="hidden items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[11px] font-mono text-muted-foreground lg:inline-flex">
                <FolderOpen size={12} /> {pasta}
              </span>
            )}
            <Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} loading={loading} onClick={() => void carregarLista()}>
              Atualizar
            </Button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <Tabs value={tab} onValueChange={(v) => setTab(v as "ficheiros" | "cae")} className="w-full">
          <TabsList className="mb-4">
            <TabsTrigger value="ficheiros" active={tab === "ficheiros"} onClick={() => setTab("ficheiros")}>
              <span className="inline-flex items-center gap-1.5">
                <FileText size={14} /> Ficheiros
                <Badge variant="outline" className="ml-1">{docs.length}</Badge>
              </span>
            </TabsTrigger>
            <TabsTrigger value="cae" active={tab === "cae"} onClick={() => setTab("cae")}>
              <span className="inline-flex items-center gap-1.5">
                <Hash size={14} /> CAE-Rev.4
              </span>
            </TabsTrigger>
          </TabsList>

          {/* ---------------------------------------------------- ficheiros */}
          <TabsContent value="ficheiros" active={tab === "ficheiros"} className="space-y-4">
            {erro && (
              <Card>
                <CardContent className="text-sm text-red-300">Não foi possível ler a pasta de documentos: {erro}</CardContent>
              </Card>
            )}

            {loading && !docs.length && (
              <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" /> A carregar documentos...
              </div>
            )}

            {!loading && !docs.length && !erro && (
              <Card>
                <CardContent className="p-8 text-center text-sm text-muted-foreground">
                  A pasta <span className="font-mono text-xs">{pasta || "data/docs"}</span> não tem documentos.
                </CardContent>
              </Card>
            )}

            {docAtual ? (
              <Card>
                <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Button variant="ghost" size="sm" icon={<ArrowLeft size={14} />} onClick={() => { setDocAtual(null); setAberto(null); setErroDoc(null); }}>
                      Voltar
                    </Button>
                    {aberto?.title ?? docAtual}
                    {aberto && <Badge variant="info">{aberto.kind}</Badge>}
                  </CardTitle>
                  <div className="flex items-center gap-2">
                    {aberto && (
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<Download size={14} />}
                        onClick={() => downloadText(`${aberto.title || aberto.name}.md`, aberto.markdown)}
                      >
                        Descarregar .md
                      </Button>
                    )}
                    <a
                      href={docFileUrl(docAtual)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-foreground transition hover:bg-accent"
                    >
                      <ExternalLink size={13} /> Abrir original
                    </a>
                  </div>
                </CardHeader>
                <CardContent>
                  {carregandoDoc && (
                    <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                      <Loader2 size={16} className="animate-spin" /> A ler o documento...
                    </div>
                  )}
                  {erroDoc && <p className="py-4 text-sm text-amber-300">{erroDoc}</p>}
                  {aberto && (
                    <div className="max-h-[70vh] overflow-y-auto rounded-xl border border-white/5 bg-black/10 p-4">
                      <MarkdownView markdown={aberto.markdown} />
                    </div>
                  )}
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {docs.map((doc) => (
                  <Card key={doc.name} className="flex flex-col justify-between">
                    <CardHeader>
                      <CardTitle className="flex items-start gap-2 text-sm">
                        <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/5 text-amber-300">
                          {doc.has_markdown ? <FileCode2 size={15} /> : <FileText size={15} />}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate">{doc.title}</span>
                          <span className="block truncate font-mono text-[11px] font-normal text-muted-foreground">{doc.name}</span>
                        </span>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        <Badge variant="default">{doc.kind}</Badge>
                        <span>{formatBytes(doc.size)}</span>
                        <span>·</span>
                        <span>{formatDate(doc.modified)}</span>
                        {doc.has_markdown && <Badge variant="success">markdown</Badge>}
                        {doc.generated && <Badge variant="secondary">gerado</Badge>}
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          icon={<FileCode2 size={13} />}
                          disabled={!doc.has_markdown}
                          onClick={() => void abrirDocumento(doc.name)}
                        >
                          {doc.has_markdown ? "Ver markdown" : "Sem markdown"}
                        </Button>
                        <a
                          href={docFileUrl(doc.name)}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs transition hover:bg-accent"
                        >
                          <ExternalLink size={13} /> Abrir
                        </a>
                        <a
                          href={docFileUrl(doc.name, true)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs transition hover:bg-accent"
                        >
                          <Download size={13} />
                        </a>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </TabsContent>

          {/* ---------------------------------------------------------- CAE */}
          <TabsContent value="cae" active={tab === "cae"} className="space-y-4">
            {erroCae && <Card><CardContent className="text-sm text-amber-300">{erroCae}</CardContent></Card>}
            {!caeMd && !erroCae && (
              <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" /> A carregar a classificação CAE-Rev.4...
              </div>
            )}

            {cae && (
              <>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <Layers size={14} />
                  <Badge variant="info">{cae.counts["Secção"] ?? 0} secções</Badge>
                  <Badge variant="default">{cae.counts["Divisão"] ?? 0} divisões</Badge>
                  <Badge variant="default">{cae.counts["Grupo"] ?? 0} grupos</Badge>
                  <Badge variant="default">{cae.counts["Classe"] ?? 0} classes</Badge>
                  <Badge variant="default">{cae.counts["Subclasse"] ?? 0} subclasses</Badge>
                  {caeDoc && (
                    <a
                      href={docFileUrl(caeDoc.name)}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs transition hover:bg-accent"
                    >
                      <ExternalLink size={13} /> Abrir PDF original
                    </a>
                  )}
                </div>

                <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
                  <Card className="lg:max-h-[70vh] lg:overflow-y-auto">
                    <CardHeader>
                      <CardTitle className="text-sm">Índice</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2">
                      <div className="relative">
                        <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                        <Input
                          autoComplete="off"
                          value={pesquisa}
                          onChange={(event) => setPesquisa(event.target.value)}
                          placeholder="Código ou designação..."
                          className="pl-8"
                        />
                      </div>
                      <div className="space-y-1">
                        {cae.sections.map((section, index) => (
                          <button
                            key={section.letter}
                            type="button"
                            onClick={() => {
                              setSeccaoAtiva(index);
                              setPesquisa("");
                            }}
                            className={`w-full rounded-lg px-2.5 py-2 text-left text-xs transition ${
                              index === seccaoAtiva && !pesquisa
                                ? "bg-primary/15 text-foreground"
                                : "text-muted-foreground hover:bg-accent hover:text-foreground"
                            }`}
                          >
                            <span className="mr-2 inline-grid h-5 w-5 place-items-center rounded-md bg-white/5 font-mono text-[11px] text-amber-300">
                              {section.letter}
                            </span>
                            <span className="align-middle">{section.title}</span>
                            <span className="mt-0.5 block pl-7 text-[10.5px] text-muted-foreground">
                              {section.intro ? "enquadramento do quadro" : plural(section.divisions, "divisão", "divisões")}
                            </span>
                          </button>
                        ))}
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="lg:max-h-[70vh] lg:overflow-y-auto">
                    {pesquisa.trim().length >= 2 ? (
                      <>
                        <CardHeader>
                          <CardTitle className="text-sm">
                            {resultados.length} resultado{resultados.length === 1 ? "" : "s"} para «{pesquisa.trim()}»
                          </CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-1.5">
                          {resultados.length === 0 && (
                            <p className="py-6 text-center text-sm text-muted-foreground">
                              Sem códigos nem designações com «{pesquisa.trim()}».
                            </p>
                          )}
                          {resultados.map((entry, index) => (
                            <button
                              key={`${entry.code}-${index}`}
                              type="button"
                              onClick={() => {
                                const alvo = cae.sections.findIndex((section) => section.letter === entry.section);
                                if (alvo >= 0) setSeccaoAtiva(alvo);
                                setPesquisa("");
                              }}
                              className="flex w-full items-start gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 text-left transition hover:border-primary/40 hover:bg-white/[0.05]"
                            >
                              <span className="mt-0.5 rounded-md bg-white/5 px-1.5 py-0.5 font-mono text-[11.5px] text-amber-300">
                                {entry.code}
                              </span>
                              <span className="min-w-0">
                                <span className="block text-[13px] text-foreground">{entry.name}</span>
                                <span className="block text-[11px] text-muted-foreground">
                                  {entry.level}
                                  {entry.path ? ` · ${entry.path}` : ""}
                                </span>
                              </span>
                            </button>
                          ))}
                        </CardContent>
                      </>
                    ) : (
                      <>
                        <CardHeader>
                          <CardTitle className="text-sm">
                            {seccao ? `Secção ${seccao.letter} — ${seccao.title}` : "Classificação"}
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          {seccao && (
                            <MarkdownView
                              markdown={seccao.intro ? seccao.body : seccao.body.split("\n").slice(1).join("\n")}
                            />
                          )}
                          <div className="mt-4 flex justify-end">
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={!caeMd}
                              icon={<Download size={13} />}
                              onClick={() => caeMd && downloadText("CAE-Rev.4.md", caeMd)}
                            >
                              Descarregar markdown completo
                            </Button>
                          </div>
                        </CardContent>
                      </>
                    )}
                  </Card>
                </div>
              </>
            )}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
