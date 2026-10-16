/**
 * Estado do cabeçalho e rodapé públicos da plataforma.
 *
 * Uma leitura por carregamento de página: a entrada (`/`) e a landing (`/login`)
 * pedem o mesmo documento e ele não muda sem recarregar — guardar a promessa
 * evita dois pedidos a mudar de página dentro da mesma sessão.
 *
 * Uma falha de rede não fica presa: devolve-se a predefinição local e a próxima
 * montagem volta a tentar, para que uma API em baixo não deixe as páginas de
 * entrada sem cabeçalho.
 */
import { useEffect, useState } from "react";

import { DEFAULT_APP_SHELL, getAppShell, type AppShell } from "./appShellApi";

let promessa: Promise<AppShell> | null = null;

function carregarShell(): Promise<AppShell> {
  if (!promessa) {
    promessa = getAppShell().catch(() => {
      promessa = null;
      return DEFAULT_APP_SHELL;
    });
  }
  return promessa;
}

export function useAppShell(): AppShell {
  const [shell, setShell] = useState<AppShell>(DEFAULT_APP_SHELL);

  useEffect(() => {
    let vivo = true;
    void carregarShell().then((valor) => {
      if (vivo) setShell(valor);
    });
    return () => {
      vivo = false;
    };
  }, []);

  return shell;
}
