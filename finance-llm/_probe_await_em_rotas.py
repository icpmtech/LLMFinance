"""Procura rotas que chamam funções `async` sem `await`.

O bug que isto caça: uma rota síncrona (`def` em vez de `async def`) que devolve
`return funcao_async(...)` — devolve a **corrotina** e o FastAPI só rebenta na
validação da resposta, com um erro que aponta para a serialização e não para a
chamada («Input should be a valid dictionary or object to extract fields from»),
mais um `RuntimeWarning: coroutine '…' was never awaited` nos logs.

Também assinala `await` em falta **dentro** de funções `async` (o mesmo sintoma,
sem o erro de validação a denunciar).

    python _probe_await_em_rotas.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

RAIZ = Path("api")
METODOS_HTTP = {"get", "post", "put", "patch", "delete", "head", "options"}


def _async_do_ficheiro(arvore: ast.Module) -> Set[str]:
    """Nomes das funções `async` definidas **neste** ficheiro."""
    return {no.name for no in ast.walk(arvore) if isinstance(no, ast.AsyncFunctionDef)}


def _async_importados(arvore: ast.Module, asyncs_por_modulo: Dict[str, Set[str]]) -> Set[str]:
    """Nomes que este módulo usa e que são `async def` no módulo de origem.

    Resolver o nome **no módulo** é o que evita os falsos positivos: `search()`,
    `run()`, `plan()` e `topic()` existem síncronos num serviço e async noutro, e
    uma comparação só por nome deu 76 «problemas» dos quais nenhum era real.
    """
    nomes: Set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module:
            origem = asyncs_por_modulo.get(no.module)
            if not origem:
                continue
            for alias in no.names:
                if alias.name in origem:
                    nomes.add(alias.asname or alias.name)
    return nomes


def _e_rota(no: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorador in no.decorator_list:
        alvo = decorador.func if isinstance(decorador, ast.Call) else decorador
        if isinstance(alvo, ast.Attribute) and alvo.attr in METODOS_HTTP:
            return True
    return False


def _chamadas_sem_await(no: ast.AST, asyncs: Set[str], pais: Dict[int, ast.AST]) -> List[Tuple[str, int]]:
    """Chamadas a async cujo resultado é **devolvido** ou **descartado**.

    Só essas são bug: uma corrotina guardada numa variável (`t = coro()`) é para
    ser aguardada mais tarde, e passada a `gather`/`wait_for`/`create_task`/
    `StreamingResponse` é o padrão correto. Foi por isso que a lista passou de 76
    para 23 e depois para 0: os restantes eram todas corrotinas bem usadas.
    """
    achados: List[Tuple[str, int]] = []
    for filho in ast.walk(no):
        if not isinstance(filho, ast.Call):
            continue
        if not isinstance(filho.func, ast.Name) or filho.func.id not in asyncs:
            continue
        pai = pais.get(id(filho))
        devolvida = isinstance(pai, ast.Return) and pai.value is filho
        descartada = isinstance(pai, ast.Expr) and pai.value is filho
        if devolvida or descartada:
            achados.append((filho.func.id, filho.lineno))
    return achados


def _mapa_de_pais(arvore: ast.Module) -> Dict[int, ast.AST]:
    """`id(no)` -> nó pai, para se poder olhar para o contexto da chamada."""
    pais: Dict[int, ast.AST] = {}
    for pai in ast.walk(arvore):
        for filho in ast.iter_child_nodes(pai):
            pais[id(filho)] = pai
    return pais


def _linhas_com_await(arvore: ast.Module) -> Set[int]:
    """Números de linha das chamadas que já estão dentro de um `await`."""
    linhas: Set[int] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Await):
            for filho in ast.walk(no.value):
                if isinstance(filho, ast.Call):
                    linhas.add(filho.lineno)
    return linhas


def main() -> int:
    arvores: Dict[Path, ast.Module] = {}
    for caminho in sorted(RAIZ.rglob("*.py")):
        try:
            arvores[caminho] = ast.parse(caminho.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as erro:
            print(f"(salta {caminho}: {erro})")

    # Nome qualificado ("api.elasticsearch_ingest") -> funções async desse módulo.
    asyncs_por_modulo: Dict[str, Set[str]] = {}
    for caminho, arvore in arvores.items():
        relativo = caminho.relative_to(RAIZ.parent).with_suffix("")
        asyncs_por_modulo[".".join(relativo.parts)] = _async_do_ficheiro(arvore)

    problemas = 0
    for caminho, arvore in arvores.items():
        awaitadas = _linhas_com_await(arvore)
        pais = _mapa_de_pais(arvore)
        asyncs = _async_do_ficheiro(arvore) | _async_importados(arvore, asyncs_por_modulo)
        for no in ast.walk(arvore):
            if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            sincrona = isinstance(no, ast.FunctionDef)
            if sincrona and not _e_rota(no):
                continue  # há muitas funções auxiliares síncronas de propósito
            for nome, linha in _chamadas_sem_await(no, asyncs, pais):
                if linha in awaitadas:
                    continue
                tipo = "ROTA SINCRONA" if sincrona else "SEM AWAIT"
                print(f"{tipo}: {caminho}:{linha} {no.name}() chama {nome}()")
                problemas += 1

    print(f"funcoes async conhecidas: {sum(len(v) for v in asyncs_por_modulo.values())} em {len(arvores)} ficheiros")
    print(f"total: {problemas} chamada(s) suspeita(s)")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
