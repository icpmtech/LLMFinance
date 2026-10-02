@echo off
cd /d C:\LLMFinance
echo ==== arranque %DATE% %TIME% ==== >> C:\LLMFinance\_tunnel_docker.err.log
cloudflared tunnel --url http://127.0.0.1:4180 --no-autoupdate >> C:\LLMFinance\_tunnel_docker.log 2>> C:\LLMFinance\_tunnel_docker.err.log
