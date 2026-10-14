"""Diagnóstico: onde estão as chaves de pagamento dentro do contentor.

Uso (dentro do backend):  docker exec finance-llm-backend python /tmp/_check_docker_keys.py
"""
import os

KEYS = [
    "PAYPAL_CLIENT_ID",
    "PAYPAL_CLIENT_SECRET",
    "PAYPAL_BASE_URL",
    "STRIPE_SECRET_KEY",
    "TRANSFER_IBAN",
    "MBWAY_NUMBER",
    "MBWAY_API_KEY",
    "PUBLIC_APP_URL",
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_FROM",
]


def main() -> None:
    print("=== 1. ambiente do processo que corre este script (os.environ) ===")
    for key in KEYS:
        value = os.environ.get(key)
        print(f"  {key:22} = {'definido' if value else 'ausente'}")

    print()
    print("=== 2. ambiente do processo principal da API (/proc/1/environ) ===")
    try:
        with open("/proc/1/environ", "rb") as handle:
            raw = handle.read().decode("utf-8", "ignore")
        env = dict(
            item.split("=", 1) for item in raw.split("\0") if "=" in item
        )
        for key in KEYS:
            value = env.get(key)
            print(f"  {key:22} = {'definido' if value else 'ausente'}")
    except OSError as exc:
        print(f"  não foi possível ler /proc/1/environ: {exc}")

    print()
    print("=== 3. ficheiro /app/.env ===")
    path = "/app/.env"
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="ignore") as handle:
            lines = [
                line.strip()
                for line in handle
                if "=" in line and not line.strip().startswith("#")
            ]
        names = {line.split("=", 1)[0].strip() for line in lines}
        for key in KEYS:
            print(f"  {key:22} = {'presente' if key in names else 'ausente'}")
    else:
        print("  /app/.env não existe")

    print()
    print("=== 4. resolução efetiva pelo billing/notification (índice → ambiente → .env) ===")
    try:
        from api import service_keys

        pares = [
            ("paypal_client_id", "PAYPAL_CLIENT_ID"),
            ("paypal_client_secret", "PAYPAL_CLIENT_SECRET"),
            ("paypal_base_url", "PAYPAL_BASE_URL"),
            ("stripe_secret_key", "STRIPE_SECRET_KEY"),
            ("transfer_iban", "TRANSFER_IBAN"),
            ("mbway_number", "MBWAY_NUMBER"),
            ("mbway_api_key", "MBWAY_API_KEY"),
            ("smtp_host", "SMTP_HOST"),
            ("smtp_user", "SMTP_USER"),
            ("smtp_from", "SMTP_FROM"),
        ]
        for key_id, env_name in pares:
            try:
                origem = service_keys.origem(key_id)
                valor = origem.get("valor")
                estado = "definido" if valor else "AUSENTE"
                print(f"  {env_name:22} = {estado:8} (origem: {origem.get('origem')})")
            except Exception as exc:  # noqa: BLE001
                print(f"  {env_name:22} = erro: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"  não foi possível importar service_keys: {exc}")


if __name__ == "__main__":
    main()
