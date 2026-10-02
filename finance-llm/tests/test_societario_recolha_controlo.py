"""Controlo dos trabalhos de recolha societária: pausar, retomar e parar.

Regressão de 2026-10-02: um trabalho de recolha corre no servidor (thread em
segundo plano) e não havia forma de o interromper — a única saída era reiniciar
a API, o que perde o registo dos trabalhos (vivem em memória).

O controlo tem duas peças, e as duas importam:

* o serviço (`api/societario_recolha.py`) marca o trabalho como `paused`/`stopped`
  e usa uma `Event` por trabalho (`set` = pode correr, `clear` = pausado);
* o coletor (`collectors/publicacoes_mj.py`) tem de **deixar subir** as exceções
  `RecolhaPausada`/`RecolhaParada` lançadas pelo callback de progresso — o
  `avisar` engolia tudo com um `except Exception` largo, pelo que uma pausa a
  meio de uma entidade grande (minutos) não teria efeito nenhum.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import pytest

from api import societario_recolha as recolha
from api import societario_service
from collectors import publicacoes_mj as pj
from collectors import publicacoes_mj_captcha

JOB_ID = "teste-controlo"


@pytest.fixture()
def job_falso() -> Dict[str, Any]:
    """Um trabalho com controlo no registo do módulo (limpo no fim do teste)."""
    job: Dict[str, Any] = {
        "job_id": JOB_ID,
        "status": recolha._RUNNING,
        "stop_requested": False,
        "payload": {"ingest": False},
        "progress": {"phase": "a recolher", "entities_total": 0},
        "result": None,
        "error": None,
    }
    evento = threading.Event()
    evento.set()
    with recolha._JOBS_LOCK:
        recolha._JOBS[JOB_ID] = job
        recolha._CONTROL[JOB_ID] = evento
    try:
        yield job
    finally:
        with recolha._JOBS_LOCK:
            recolha._JOBS.pop(JOB_ID, None)
            recolha._CONTROL.pop(JOB_ID, None)


def test_pausar_para_a_thread_e_retomar_liberta(job_falso: Dict[str, Any]) -> None:
    recolha.pause_job(JOB_ID)
    assert job_falso["status"] == "paused"
    assert job_falso["progress"]["phase"] == "pausado pelo utilizador"
    assert recolha._CONTROL[JOB_ID].is_set() is False
    with pytest.raises(pj.RecolhaPausada):
        recolha._checkpoint(job_falso)

    recolha.resume_job(JOB_ID)
    assert job_falso["status"] == "running"
    assert recolha._CONTROL[JOB_ID].is_set() is True
    recolha._checkpoint(job_falso)  # não levanta
    assert recolha._aguardar_retoma(job_falso) is True


def test_parar_desbloqueia_um_trabalho_pausado(job_falso: Dict[str, Any]) -> None:
    recolha.pause_job(JOB_ID)
    recolha.stop_job(JOB_ID)

    # O pedido de paragem liberta a `Event`, senão a thread ficava presa à espera
    # de uma retoma que nunca vem.
    assert recolha._CONTROL[JOB_ID].is_set() is True
    assert recolha._aguardar_retoma(job_falso) is False
    with pytest.raises(pj.RecolhaParada):
        recolha._checkpoint(job_falso)


def test_terminar_por_pedido_preserva_o_que_foi_recolhido(job_falso: Dict[str, Any]) -> None:
    job_falso["progress"]["entities_total"] = 4
    recolha._terminar_por_pedido(job_falso, [{"nif": "1"}], 12, 1, 0, [])

    assert job_falso["status"] == "stopped"
    assert job_falso["finished_at"]
    assert job_falso["progress"]["phase"] == "parado pelo utilizador"
    assert job_falso["result"]["publications"] == 12
    assert job_falso["result"]["entities_with_publications"] == 1
    assert "Interrompido" in job_falso["result"]["message"]


def test_controlo_de_trabalho_inexistente() -> None:
    assert recolha.pause_job("nao-existe") is None
    assert recolha.resume_job("nao-existe") is None
    assert recolha.stop_job("nao-existe") is None


def _cliente_sem_rede(monkeypatch: pytest.MonkeyPatch) -> pj.PublicacoesMjClient:
    """Cliente do portal com a pesquisa substituída (nenhum pedido à rede)."""
    cliente = pj.PublicacoesMjClient()
    monkeypatch.setattr(cliente, "fetch_form", lambda: "<form></form>")
    monkeypatch.setattr(cliente, "search", lambda *args, **kwargs: ([], "<html></html>"))
    return cliente


def test_pausa_no_progresso_interrompe_a_recolha(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _cliente_sem_rede(monkeypatch)

    def interromper(evento: Dict[str, Any]) -> None:
        raise pj.RecolhaPausada("pausa pedida pelo utilizador")

    with pytest.raises(pj.RecolhaPausada):
        cliente.collect(recaptcha_token="tok", with_details=False, on_progress=interromper)


def test_paragem_no_progresso_interrompe_a_recolha(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _cliente_sem_rede(monkeypatch)

    def parar(evento: Dict[str, Any]) -> None:
        raise pj.RecolhaParada("paragem pedida pelo utilizador")

    with pytest.raises(pj.RecolhaParada):
        cliente.collect(recaptcha_token="tok", with_details=False, on_progress=parar)


def test_falha_do_progresso_continua_a_ser_engolida(monkeypatch: pytest.MonkeyPatch) -> None:
    """Um erro qualquer no callback de progresso não pode estragar a recolha."""
    cliente = _cliente_sem_rede(monkeypatch)

    def estragar(evento: Dict[str, Any]) -> None:
        raise RuntimeError("progresso avariado")

    assert cliente.collect(recaptcha_token="tok", with_details=False, on_progress=estragar) == []


# ---------------------------------------------------------------------------
# O ciclo completo do trabalho (pausar → retomar → parar), com coletor falso
# ---------------------------------------------------------------------------

class PublicacaoFalsa:
    """Publicação mínima: o `to_dict` é o que o serviço usa para gravar."""

    def __init__(self, indice: int) -> None:
        self.pub_id = f"fake-{indice}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pub_id": self.pub_id,
            "nif": "500000000",
            "firma": "TESTE, S.A.",
            "data_publicacao": "2026-01-01",
        }


class ClienteFalso:
    """Coletor lento que emite progresso — dá tempo a pausar a meio da entidade."""

    passos = 40
    pausa_por_passo = 0.05

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def collect(
        self,
        *,
        with_details: bool = True,
        max_pages: int = 1,
        on_progress: Optional[Any] = None,
        on_page: Optional[Any] = None,
        **criteria: Any,
    ) -> List[PublicacaoFalsa]:
        publicacoes: List[PublicacaoFalsa] = []
        for i in range(self.passos):
            time.sleep(self.pausa_por_passo)
            if on_progress is not None:
                on_progress(
                    {
                        "stage": "detalhes",
                        "details_done": i + 1,
                        "details_total": self.passos,
                        "publications": self.passos,
                    }
                )
            publicacoes.append(PublicacaoFalsa(i))
        return publicacoes


def _esperar(condicao: Any, timeout: float = 10.0) -> bool:
    limite = time.time() + timeout
    while time.time() < limite:
        if condicao():
            return True
        time.sleep(0.05)
    return False


def _detalhes(job_id: str) -> int:
    job = recolha.job_status(job_id) or {}
    atual = (job.get("progress") or {}).get("current") or {}
    return int(atual.get("details_done") or 0)


def _estabilizar(job_id: str, timeout: float = 5.0) -> int:
    """Espera que o progresso pare (a pausa é apanhada no ponto de controlo seguinte).

    Necessário porque `pause_job` marca o trabalho como pausado **logo**, mas a
    thread só para no próximo evento de progresso — uma janela fixa de tempo
    dava um teste intermitente.
    """
    valor = _detalhes(job_id)
    limite = time.time() + timeout
    while time.time() < limite:
        time.sleep(0.2)
        novo = _detalhes(job_id)
        if novo == valor:
            return valor
        valor = novo
    raise AssertionError("o progresso não estabilizou depois de pausar")


@pytest.fixture()
def ambiente_recolha(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """Trabalho isolado: alvo fixo, coletor falso, sem Elasticsearch nem portal."""
    with recolha._JOBS_LOCK:
        recolha._JOBS.clear()
        recolha._CONTROL.clear()
    monkeypatch.setenv("SOCIETARIO_EXPORT_DIR", str(tmp_path))
    monkeypatch.setattr(
        recolha,
        "targets",
        lambda **kwargs: {"items": [{"nif": "500000000", "name": "TESTE, S.A."}], "filters": {}},
    )
    monkeypatch.setattr(publicacoes_mj_captcha, "PublicacoesMjCaptchaClient", ClienteFalso)
    monkeypatch.setattr(societario_service, "ingest", lambda *a, **k: {"indexed_count": 0, "total": 0})
    yield
    for job in list(recolha._JOBS.values()):
        recolha.stop_job(str(job["job_id"]))
    time.sleep(0.2)


def test_pausar_retomar_e_parar_um_trabalho_a_correr(ambiente_recolha: Any) -> None:
    job = recolha.start_job(
        {"nifs": ["500000000"], "max_entities": 1, "with_details": True, "ingest": False, "min_interval": 0}
    )
    job_id = job["job_id"]

    assert _esperar(lambda: _detalhes(job_id) >= 3), "a recolha não chegou aos detalhes"

    # ── pausar: o progresso tem de parar ────────────────────────────────
    recolha.pause_job(job_id)
    assert _esperar(lambda: recolha.job_status(job_id)["status"] == "paused")
    congelado = _estabilizar(job_id)
    time.sleep(0.6)
    assert _detalhes(job_id) == congelado, "o trabalho continuou a avançar depois de pausado"

    # ── retomar: volta a avançar ────────────────────────────────────────
    recolha.resume_job(job_id)
    assert _esperar(lambda: _detalhes(job_id) > congelado), "o trabalho não retomou"
    assert recolha.job_status(job_id)["status"] == "running"

    # ── parar: fecha, mas guarda o que já recolheu ──────────────────────
    recolha.stop_job(job_id)
    assert _esperar(lambda: recolha.job_status(job_id)["status"] == "stopped")
    final = recolha.job_status(job_id) or {}
    assert final["progress"]["phase"] == "parado pelo utilizador"
    assert "Interrompido" in (final["result"] or {}).get("message", "")
    assert final["finished_at"]

