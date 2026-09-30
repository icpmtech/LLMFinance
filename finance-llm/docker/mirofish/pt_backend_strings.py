"""Traduz para português as mensagens do backend do MiroFish que aparecem na UI.

A interface do MiroFish vem de `locales/*.json` (já temos `pt.json`), mas há
mensagens construídas **no código** que chegam ao utilizador tal e qual: o
progresso da geração de personas («已完成 4/32: …»), o progresso do relatório e
os erros de operação devolvidos pela API (simulação inexistente, a correr,
plataforma inválida, …).

Este script aplica substituições literais (os textos originais são f-strings em
chinês, portanto as chaves `{}` fazem parte do texto a substituir) e é
idempotente: o que já estiver traduzido não é tocado.

Correr dentro do contentor (feito na build da imagem, ver `Dockerfile`).
"""
from __future__ import annotations

import pathlib
import sys

SERVICES = pathlib.Path("/app/backend/app/services")

#: Obrigatório: se este texto desaparecer do upstream, quer dizer que a mensagem
#: de progresso mudou e que a tradução deixou de a apanhar — vale a pena falhar
#: a build em vez de mostrar chinês ao utilizador.
REQUIRED = [
    'f"已完成 {current}/{total}: {entity.name}（{entity_type}）"',
]

#: (ficheiro, original, tradução). Aplicadas por ordem; várias por ficheiro.
REPLACEMENTS: list[tuple[str, str, str]] = [
    # --- progresso visível na página de simulação -------------------------
    (
        "oasis_profile_generator.py",
        'f"已完成 {current}/{total}: {entity.name}（{entity_type}）"',
        'f"{current}/{total} concluídos: {entity.name} ({entity_type})"',
    ),
    (
        "oasis_profile_generator.py",
        'f"开始生成Agent人设 - 共 {total} 个实体， 并行数: {parallel_count}"',
        'f"A gerar os perfis dos agentes — {total} entidades, {parallel_count} em paralelo"',
    ),
    (
        "oasis_profile_generator.py",
        'f"人设生成完成！共生成 {len([p for p in profiles if p])} 个Agent"',
        'f"Perfis gerados: {len([p for p in profiles if p])} agentes"',
    ),
    # --- erros de operação devolvidos pela API ----------------------------
    ("simulation_manager.py", 'f"模拟不存在: {simulation_id}"', 'f"Simulação não encontrada: {simulation_id}"'),
    ("simulation_manager.py", 'f"不支持的平台: {platform}"', 'f"Plataforma não suportada: {platform}"'),
    ("simulation_manager.py", 'f"模拟不存在: {simulation_id}"', 'f"Simulação não encontrada: {simulation_id}"'),
    ("simulation_runner.py", 'f"模拟不存在: {simulation_id}"', 'f"Simulação não encontrada: {simulation_id}"'),
    (
        "simulation_runner.py",
        'f"模拟配置不存在，请先调用 /prepare  接口"',
        'f"A configuração da simulação não existe — chame primeiro /api/simulation/prepare"',
    ),
    (
        "simulation_runner.py",
        'f"模拟已在运行或结束处理中: {simulation_id}"',
        'f"A simulação já está em execução ou a terminar: {simulation_id}"',
    ),
    (
        "simulation_runner.py",
        'f"模拟未在运行: {simulation_id}, status={state.runner_status}"',
        'f"A simulação não está em execução: {simulation_id}, estado={state.runner_status}"',
    ),
    (
        "simulation_runner.py",
        'f"模拟环境未运行或已关闭，无法执行Interview: {simulation_id}"',
        'f"O ambiente da simulação não está em execução (ou já foi fechado): não é possível entrevistar agentes em {simulation_id}"',
    ),
    (
        "simulation_runner.py",
        'f"模拟配置不存在: {simulation_id}"',
        'f"A configuração da simulação não existe: {simulation_id}"',
    ),
    (
        "simulation_runner.py",
        'f"模拟配置中没有Agent: {simulation_id}"',
        'f"A configuração da simulação não tem agentes: {simulation_id}"',
    ),
    (
        "simulation_runner.py",
        'f"Zep图谱更新器初始化失败: {e}"',
        'f"Falhou a inicialização do atualizador do grafo Zep: {e}"',
    ),
    (
        "simulation_runner.py",
        'f"Zep图谱写入未完整完成: {error}"',
        'f"A escrita no grafo Zep não terminou por completo: {error}"',
    ),
    ("simulation_runner.py", 'f"脚本不存在: {script_path}"', 'f"O script não existe: {script_path}"'),
]


def main() -> int:
    if not SERVICES.exists():
        print(f"[pt_backend_strings] diretório não encontrado: {SERVICES}", file=sys.stderr)
        return 1

    cache: dict[str, str] = {}
    failures: list[str] = []
    applied = 0

    for filename, original, translated in REPLACEMENTS:
        path = SERVICES / filename
        if not path.exists():
            failures.append(f"{filename} não existe")
            continue
        text = cache.get(filename)
        if text is None:
            text = path.read_text(encoding="utf-8")

        if translated in text:
            cache[filename] = text
            continue
        if original not in text:
            if original in REQUIRED:
                failures.append(f"texto obrigatório não encontrado em {filename}: {original}")
            cache[filename] = text
            continue

        text = text.replace(original, translated)
        cache[filename] = text
        applied += 1

    written = 0
    for filename, text in cache.items():
        path = SERVICES / filename
        current = path.read_text(encoding="utf-8")
        if current != text:
            path.write_text(text, encoding="utf-8")
            written += 1

    print(f"[pt_backend_strings] {applied} substituições em {written} ficheiros")
    if failures:
        for failure in failures:
            print(f"[pt_backend_strings] {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
