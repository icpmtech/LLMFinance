#!/command/with-contenv sh
# shellcheck shell=sh
#
# Ativação declarativa do provider de autenticação do dashboard do Hermes Agent
# que usa as contas do IQ OS.
#
# Porquê este script: os ficheiros do plugin estão num *bind mount* de leitura,
# mas o **estado de ativação** vive no `$HERMES_HOME/config.yaml` (dentro do
# volume `hermes-data`) — um `docker compose down -v` apagava-o e o dashboard
# deixava de arrancar («Refusing to bind … no auth providers are registered»).
# Ativá-lo aqui mantém o `docker-compose.yml` como fonte de verdade.
#
# Corre em todos os arranques (cont-init do s6-overlay). É idempotente: se já
# estiver ativo, o `hermes plugins enable` não altera nada.
set -e

PLUGIN="dashboard-auth-iqos"

if [ -z "${IQOS_API_URL:-}" ]; then
    echo "[iqos-plugin] IQOS_API_URL não definida — a saltar a ativação de ${PLUGIN}."
    exit 0
fi

# O shim `hermes` larga o root para o utilizador hermes (UID 10000), para que
# o config.yaml do volume continue a pertencer a quem lá escreve.
if s6-setuidgid hermes hermes plugins enable "${PLUGIN}" >/dev/null 2>&1; then
    echo "[iqos-plugin] ${PLUGIN} ativo — o login do dashboard é validado em ${IQOS_API_URL}/auth/login."
else
    echo "[iqos-plugin] aviso: não foi possível ativar ${PLUGIN}; o dashboard pode recusar ligar-se a 0.0.0.0."
fi
