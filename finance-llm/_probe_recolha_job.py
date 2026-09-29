"""Testar o trabalho de recolha sem tocar no portal do MJ (cliente falso)."""
from __future__ import annotations

import os
import time

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

import collectors.publicacoes_mj_captcha as captcha  # noqa: E402
from api import societario_recolha as recolha  # noqa: E402


class PublicacaoFalsa:
    def __init__(self, n: int) -> None:
        self.n = n

    def to_dict(self) -> dict:
        return {
            "pub_id": f"fake-{self.n}",
            "nif": "501506543",
            "data_publicacao": f"2024-0{self.n % 9 + 1}-1{self.n % 9}",
            "acto": "Designação de membro(s) de órgão(s) social(ais)",
            "texto": "Nome/Firma: TESTE PESSOA NIF/NIPC: 123456789 Cargo: Gerente",
        }


class ClienteFalso:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def collect(self, **kwargs):
        return [PublicacaoFalsa(1), PublicacaoFalsa(2)]


captcha.PublicacoesMjCaptchaClient = ClienteFalso  # type: ignore[assignment]

if __name__ == "__main__":
    job = recolha.start_job(
        {
            "nifs": ["501506543"],
            "max_entities": 1,
            "with_details": False,
            "max_pages": 1,
            "ingest": False,
            "exclude_collected": False,
        }
    )
    print("job:", job["job_id"], job["status"])
    for _ in range(20):
        time.sleep(1.5)
        atual = recolha.job_status(job["job_id"]) or {}
        print(
            f"  fase={atual.get('progress', {}).get('phase')} "
            f"{atual.get('progress', {}).get('entities_done')}/{atual.get('progress', {}).get('entities_total')} "
            f"pubs={atual.get('progress', {}).get('publications')} status={atual.get('status')}"
        )
        if atual.get("status") != "running":
            print("  resultado:", atual.get("result"))
            print("  erro:", atual.get("error"))
            break
    print("\nficheiros exportados:")
    for item in recolha.list_exports().get("items", []):
        print("  ", item["nif"], item.get("name"), item.get("total"), item.get("bytes"), "bytes")
