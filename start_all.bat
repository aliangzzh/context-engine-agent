@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Context Engine + Multi-Agent QA  一键启动
echo ============================================
rem 优先用项目自己的 .venv 解释器：系统 PATH 里的 python 往往没装
rem requirements-llm.txt，只填了 .env 的 key 时会**静默退回离线模型**（踩过这个坑）。
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
  echo [1/3] 正在启动后端 (Python: .venv) ...
  start "Backend 8000" cmd /k "cd /d %~dp0backend && "%VENV_PY%" run.py"
) else (
  echo [1/3] [!] 没找到 .venv，只能用系统 python 启动 —— 可能缺依赖、静默退回离线模型
  start "Backend 8000" cmd /k "cd /d %~dp0backend && python run.py"
)
echo [2/3] 正在启动前端 (Node) ...
start "Frontend 5173" cmd /k "cd /d %~dp0frontend && npm.cmd run dev"
echo [3/3] 等待服务就绪，然后打开浏览器 ...
timeout /t 4 >nul
start http://localhost:5173
echo 完成。两个黑窗口请保持开启，关闭窗口即停止服务。
