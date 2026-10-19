/**
 * Tradução do conteúdo do widget Tawk.to que o pacote de idioma não cobre.
 *
 * O widget já está configurado em português (`language: "pt"`), mas o nome do
 * agente, a saudação e as respostas sugeridas são conteúdo personalizado e
 * chegam sempre em inglês. O iframe do Tawk é same-origin (`about:srcdoc`), por
 * isso o DOM pode ser traduzido depois de carregar. O mapa é o mesmo de
 * `api/tawk.py` (site e loja, servidos pelo backend).
 */
const TRADUCOES: Record<string, string> = {
  "Customer Support": "Apoio ao cliente",
  "Hi! How can we help?": "Olá! Em que podemos ajudar?",
  "👋 Hi! How can we help?": "👋 Olá! Em que podemos ajudar?",
  "I have a question": "Tenho uma pergunta",
  "Tell me more": "Quero saber mais",
  "Suggested replies": "Respostas sugeridas",
  "Suggested messages": "Mensagens sugeridas",
  Messages: "Mensagens",
  "New messages": "Mensagens novas",
  Minimize: "Minimizar",
  Restore: "Restaurar",
  Close: "Fechar",
  Back: "Voltar",
  "Rate this chat": "Avaliar esta conversa",
  "Rate this conversation with -1": "Avaliar esta conversa com -1",
  "Rate this conversation with +1": "Avaliar esta conversa com +1",
  "Upload File": "Carregar ficheiro",
  "Insert emoji": "Inserir emoji",
  "Send message": "Enviar mensagem",
  "Chat widget": "Chat",
  "Opens Chat This icon Opens the chat window.": "Abrir a janela de chat",
  "Group of buttons": "Grupo de botões",
  Away: "Ausente",
  Name: "Nome",
  Message: "Mensagem",
  "Search for answers": "Pesquisar respostas",
  "Help Center": "Centro de ajuda",
  "Recent conversations": "Conversas recentes",
};

const ATRIBUTOS = ["aria-label", "title", "placeholder", "alt"] as const;

let instalado = false;

function traduzir(valor: string | null): string | null {
  if (!valor) return null;
  return TRADUCOES[valor.trim()] ?? null;
}

function percorrer(raiz: HTMLElement): void {
  raiz.querySelectorAll<HTMLElement>("*").forEach((el) => {
    if (el.matches('input, textarea, [contenteditable="true"]')) return;
    ATRIBUTOS.forEach((atributo) => {
      const novo = traduzir(el.getAttribute(atributo));
      if (novo) el.setAttribute(atributo, novo);
    });
  });

  const walker = raiz.ownerDocument.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
  let no = walker.nextNode();
  while (no) {
    const original = no.nodeValue ?? "";
    const chave = original.trim();
    const novo = TRADUCOES[chave];
    if (novo) no.nodeValue = original.replace(chave, novo);
    no = walker.nextNode();
  }
}

function observar(doc: Document): boolean {
  const html = doc.documentElement;
  const body = doc.body;
  if (!html || !body) return false;
  if (html.getAttribute("data-tawk-pt") === "1") return true;

  const texto = body.textContent ?? "";
  const estado = texto.trim();
  const pareceTawk =
    texto.includes("tawk.to") ||
    estado === "Online" ||
    estado === "Away" ||
    estado === "Offline" ||
    Object.keys(TRADUCOES).some((chave) => texto.includes(chave));
  if (!pareceTawk) return false;

  html.setAttribute("data-tawk-pt", "1");
  percorrer(body);
  new MutationObserver(() => percorrer(body)).observe(html, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: [...ATRIBUTOS],
  });
  return true;
}

function varrer(): void {
  document.querySelectorAll("iframe").forEach((frame) => {
    let doc: Document | null = null;
    try {
      doc = frame.contentDocument;
    } catch {
      doc = null;
    }
    if (doc) observar(doc);
  });
}

export function instalarTraducaoTawk(): void {
  if (instalado || typeof window === "undefined") return;
  instalado = true;
  varrer();
  window.setInterval(varrer, 800);
}
