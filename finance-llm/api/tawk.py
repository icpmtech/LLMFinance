"""Widget de apoio ao cliente (Tawk.to) das páginas públicas.

O site do CMS (`/site/...`) e a loja (`/loja/...`) são HTML autónomo, montado no
servidor, e não passam pela SPA; a SPA (landing, login e registo) monta o mesmo
widget pelo React (`chat-ui/src/components/TawkChat.tsx`). A propriedade tem de
ser a mesma dos dois lados — é a que está configurada no painel do Tawk.to.
"""
from __future__ import annotations

#: Propriedade do Tawk.to (`<property_id>/<widget_id>`).
TAWK_PROPERTY = "6ac786035f2ded34cbd1cbeb/1k4dm7048"

#: Snippet oficial do Tawk.to, para o `<head>`. Cria o `<script>` de forma
#: assíncrona e mantém `Tawk_API`/`Tawk_LoadStart` globais, como o original.
TAWK_SNIPPET = (
    "<script>"
    "var Tawk_API=window.Tawk_API||{},Tawk_LoadStart=new Date();"
    "(function(){"
    "var s1=document.createElement('script'),s0=document.getElementsByTagName('script')[0];"
    "s1.async=true;"
    f"s1.src='https://embed.tawk.to/{TAWK_PROPERTY}';"
    "s1.charset='UTF-8';"
    "s1.setAttribute('crossorigin','*');"
    "s0.parentNode.insertBefore(s1,s0);"
    "})();"
    "</script>"
)

#: Tradução do conteúdo que o pacote de idioma do Tawk.to não cobre.
#:
#: O widget já está configurado em português (`language: "pt"`), mas o nome do
#: agente, a saudação e as respostas sugeridas são conteúdo personalizado e
#: chegam sempre em inglês. O iframe do Tawk é same-origin (`about:srcdoc`), por
#: isso o DOM pode ser traduzido depois de carregar. O mapa é o mesmo de
#: `chat-ui/src/components/tawkTraducao.ts` (páginas servidas pela SPA).
TAWK_TRADUCAO_SNIPPET = """<script>
(function () {
  var MAP = {
    "Customer Support": "Apoio ao cliente",
    "Hi! How can we help?": "Olá! Em que podemos ajudar?",
    "👋 Hi! How can we help?": "👋 Olá! Em que podemos ajudar?",
    "I have a question": "Tenho uma pergunta",
    "Tell me more": "Quero saber mais",
    "Suggested replies": "Respostas sugeridas",
    "Suggested messages": "Mensagens sugeridas",
    "Messages": "Mensagens",
    "New messages": "Mensagens novas",
    "Minimize": "Minimizar",
    "Restore": "Restaurar",
    "Close": "Fechar",
    "Back": "Voltar",
    "Rate this chat": "Avaliar esta conversa",
    "Rate this conversation with -1": "Avaliar esta conversa com -1",
    "Rate this conversation with +1": "Avaliar esta conversa com +1",
    "Upload File": "Carregar ficheiro",
    "Insert emoji": "Inserir emoji",
    "Send message": "Enviar mensagem",
    "Chat widget": "Chat",
    "Opens Chat This icon Opens the chat window.": "Abrir a janela de chat",
    "Group of buttons": "Grupo de botões",
    "Away": "Ausente",
    "Name": "Nome",
    "Message": "Mensagem",
    "Search for answers": "Pesquisar respostas",
    "Help Center": "Centro de ajuda",
    "Recent conversations": "Conversas recentes"
  };
  var ATRIBUTOS = ["aria-label", "title", "placeholder", "alt"];

  function traduzir(valor) {
    var chave = (valor || "").trim();
    return MAP[chave] || null;
  }

  function percorrer(raiz) {
    if (!raiz) return;
    var elementos = raiz.querySelectorAll("*");
    for (var i = 0; i < elementos.length; i++) {
      var el = elementos[i];
      if (el.matches('input, textarea, [contenteditable="true"]')) continue;
      for (var a = 0; a < ATRIBUTOS.length; a++) {
        var novo = traduzir(el.getAttribute(ATRIBUTOS[a]));
        if (novo) el.setAttribute(ATRIBUTOS[a], novo);
      }
    }
    var walker = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT, null);
    var no;
    while ((no = walker.nextNode())) {
      var original = no.nodeValue || "";
      var chave = original.trim();
      if (MAP[chave]) no.nodeValue = original.replace(chave, MAP[chave]);
    }
  }

  function observar(doc) {
    if (!doc || !doc.body) return false;
    if (doc.documentElement.getAttribute("data-tawk-pt") === "1") return true;
    var texto = doc.body.textContent || "";
    var pareceTawk = texto.indexOf("tawk.to") >= 0;
    if (!pareceTawk) {
      var estado = texto.trim();
      pareceTawk = estado === "Online" || estado === "Away" || estado === "Offline";
    }
    if (!pareceTawk) {
      for (var chave in MAP) {
        if (texto.indexOf(chave) >= 0) { pareceTawk = true; break; }
      }
    }
    if (!pareceTawk) return false;
    doc.documentElement.setAttribute("data-tawk-pt", "1");
    percorrer(doc.body);
    new MutationObserver(function () { percorrer(doc.body); }).observe(doc.documentElement, {
      childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ATRIBUTOS
    });
    return true;
  }

  function varrer() {
    var frames = document.querySelectorAll("iframe");
    for (var i = 0; i < frames.length; i++) {
      var doc = null;
      try { doc = frames[i].contentDocument; } catch (e) { doc = null; }
      if (doc) observar(doc);
    }
  }

  varrer();
  window.setInterval(varrer, 800);
})();
</script>"""
