@echo off
cd /d c:\LLMFinance\finance-llm
docker compose --profile mirofish build mirofish > logs\_mirofish_build.log 2>&1
echo build_exit=%ERRORLEVEL%
docker rm -f mirofish > NUL 2>&1
docker run -d --name mirofish --network finance-llm_default -p 5001:5001 -e LLM_API_KEY=sk-dummy -e ZEP_API_KEY=dummy-zep -e LLM_MODEL_NAME=gpt-4o-mini iq-os-mirofish:latest
echo run_exit=%ERRORLEVEL%
