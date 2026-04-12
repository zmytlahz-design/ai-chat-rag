@echo off
setlocal EnableExtensions
title AI Chat RAG - MCP Bridge
cd /d "%~dp0"

echo [MCP] Installing required packages ...
py -3 -m pip install --disable-pip-version-check fastapi uvicorn httpx
if errorlevel 1 (
  echo [MCP][ERROR] Failed to install dependencies.
  pause
  exit /b 1
)

echo [MCP] Starting bridge at http://localhost:9000 ...
py -3 -m uvicorn mcp_bridge:app --host 0.0.0.0 --port 9000
