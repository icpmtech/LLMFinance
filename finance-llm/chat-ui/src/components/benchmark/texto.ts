/**
 * Texto vindo dos contratos, pronto para o ecrã.
 *
 * Os nomes das entidades no índice trazem entidades HTML (`&amp;`, `&quot;`,
 * `&#39;`), porque a origem publica-os assim. Sem isto, o ecrã mostra
 * «JOHNSON &amp; JOHNSON» em vez de «JOHNSON & JOHNSON».
 */
const ENTIDADES: Record<string, string> = {
  "&amp;": "&",
  "&quot;": '"',
  "&#39;": "'",
  "&apos;": "'",
  "&lt;": "<",
  "&gt;": ">",
  "&nbsp;": " ",
};

export function limparNome(nome?: string | null): string {
  if (!nome) return "";
  return nome
    .replace(/&(amp|quot|#39|apos|lt|gt|nbsp);/g, (achado) => ENTIDADES[achado] ?? achado)
    .replace(/&amp;/g, "&")
    .trim();
}

/** Formas sociais e palavras genéricas que não servem de iniciais. */
const RUIDO =
  /^(lda|sa|s\.a|sl|s\.l|sas|sarl|eurl|unipessoal|unip|ltd|inc|gmbh|bv|nv|plc|co|company|grupo|group|sociedade|empresa|the|de|da|do|das|dos|e|y|el|la|los|et|des|du|of|and)$/i;

/**
 * Iniciais para o avatar de uma empresa: `JOHNSON & JOHNSON` → `JJ`,
 * `MERCK SHARP & DOHME` → `MS`. Usadas quando ainda não há logótipo.
 */
export function iniciais(nome?: string | null): string {
  const palavras = limparNome(nome)
    .replace(/[^\p{L}\p{N}\s&.-]/gu, " ")
    .split(/[\s&.]+/)
    .filter((palavra) => palavra.length > 1 && !RUIDO.test(palavra));
  if (!palavras.length) return (limparNome(nome).trim().slice(0, 2) || "?").toUpperCase();
  if (palavras.length === 1) return palavras[0].slice(0, 2).toUpperCase();
  return (palavras[0][0] + palavras[1][0]).toUpperCase();
}

/** Cor estável por empresa (para o avatar sem logótipo nunca mudar). */
export function corDaEmpresa(nome?: string | null): string {
  const paleta = ["#38bdf8", "#34d399", "#f59e0b", "#a78bfa", "#fb7185", "#22d3ee", "#f472b6", "#84cc16"];
  let soma = 0;
  const texto = limparNome(nome) || "?";
  for (let indice = 0; indice < texto.length; indice += 1) soma = (soma * 31 + texto.charCodeAt(indice)) % 100003;
  return paleta[soma % paleta.length];
}
