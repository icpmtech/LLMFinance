# Pasta partilhada com o container do n8n (montada em `/files`).
#
# Serve para importar/exportar workflows e ficheiros de dados à mão:
#   docker compose exec n8n n8n import:workflow --input=/files/meu-workflow.json
#   docker compose exec n8n n8n export:workflow --all --output=/files/backup.json
