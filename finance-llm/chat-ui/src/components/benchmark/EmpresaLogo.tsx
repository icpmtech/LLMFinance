/**
 * **Logótipo da empresa** (com avatar de recurso).
 *
 * O logótipo é servido pelo backend na rota `/api/empresas/perfil/<nif>/logo`,
 * que devolve um PNG quadrado 256×256 já normalizado. Se ainda não houver
 * logótipo — empresa nova, site sem marca legível ou falha de rede — mostra-se
 * um avatar com as **iniciais** e uma cor estável, para o ecrã nunca ficar com
 * um espaço vazio.
 */
import { useEffect, useState } from "react";

import { urlLogoAbsoluto } from "../../empresasPerfil";
import { corDaEmpresa, iniciais, limparNome } from "./texto";

export default function EmpresaLogo({
  nome,
  nif,
  logoUrl,
  size = 28,
  className = "",
  titulo,
}: {
  nome?: string | null;
  nif?: string | null;
  logoUrl?: string | null;
  size?: number;
  className?: string;
  titulo?: string;
}) {
  const [falhou, setFalhou] = useState(false);
  const fonte = urlLogoAbsoluto(logoUrl) || (nif ? `/api/empresas/perfil/${nif}/logo` : null);
  const usarImagem = Boolean(fonte) && !falhou;

  // Nova empresa (ou novo URL) volta a tentar a imagem.
  useEffect(() => setFalhou(false), [fonte]);

  const rotulo = limparNome(nome) || nif || "Empresa";
  const estilo = { width: size, height: size, minWidth: size };

  if (usarImagem) {
    return (
      <span
        className={`inline-flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-white/95 ring-1 ring-black/10 ${className}`}
        style={estilo}
        title={titulo || rotulo}
      >
        <img
          src={fonte as string}
          alt={rotulo}
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          className="h-full w-full object-contain p-[2px]"
          onError={() => setFalhou(true)}
        />
      </span>
    );
  }

  const cor = corDaEmpresa(nome);
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-lg font-semibold ring-1 ring-inset ${className}`}
      style={{
        ...estilo,
        background: `${cor}22`,
        borderColor: cor,
        color: cor,
        fontSize: Math.max(9, Math.round(size * 0.42)),
        boxShadow: `inset 0 0 0 1px ${cor}55`,
      }}
      title={titulo || rotulo}
    >
      {iniciais(nome) || "?"}
    </span>
  );
}
