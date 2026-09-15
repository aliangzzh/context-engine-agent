@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Context Engine + Multi-Agent QA  一键启动
echo ============================================
echo [1/3] 正在启动后端 (Python) ...
start "Backend 8000" cmd /k "cd /d %~dp0backend && python run.py"
echo [2/3] 正在启动前端 (Node) ...
start "Frontend 5173" cmd /k "cd /d %~dp0frontend && npm.cmd run dev"
echo [3/3] 等待服务就绪，然后打开浏览器 ...
timeout /t 4 >nul
start http://localhost:5173
echo 完成。两个黑窗口请保持开启，关闭窗口即停止服务。
