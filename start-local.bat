@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=start"
if /I "%ACTION%"=="help" goto help
if /I "%ACTION%"=="--help" goto help
if /I "%ACTION%"=="-h" goto help
if /I "%ACTION%"=="start" goto check_docker
if /I "%ACTION%"=="stop" goto check_docker
if /I "%ACTION%"=="status" goto check_docker
if /I "%ACTION%"=="logs" goto check_docker
echo 未知操作：%ACTION%
exit /b 2

:help
echo 用法：start-local.bat [start^|stop^|status^|logs]
echo start 构建并启动全部服务及模拟器；stop 停止但保留数据卷。
exit /b 0

:check_docker
where docker >nul 2>&1
if errorlevel 1 (
  echo 未找到 docker 命令，请先安装 Docker Desktop。
  exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
  echo 未找到 Docker Compose 插件，请更新 Docker Desktop。
  exit /b 1
)
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready
echo Docker Desktop 尚未启动，正在尝试打开并等待 Docker 引擎…
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set /a RETRIES=0
:wait_docker
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready
set /a RETRIES+=1
if %RETRIES% GEQ 60 (
  echo 等待 Docker 超时，请在 Docker Desktop 中检查引擎状态后重试。
  exit /b 1
)
timeout /t 3 /nobreak >nul
goto wait_docker

:docker_ready
if /I "%ACTION%"=="stop" goto stop_services
if /I "%ACTION%"=="status" goto status_services
if /I "%ACTION%"=="logs" goto logs_services

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  if errorlevel 1 goto failed
  echo 已建立本地 .env；以后不会覆盖你的配置。
)
echo 正在构建本地镜像…
docker compose build
if errorlevel 1 goto failed
echo 正在启动 MQTT、Fuseki 和 Web 服务…
docker compose up -d --wait --wait-timeout 300
if errorlevel 1 goto failed
echo 正在启动演示模拟器…
docker compose --profile demo up -d --force-recreate simulator
if errorlevel 1 goto failed
docker compose --profile demo ps
set "WEB_PORT=8092"
for /f "tokens=2 delims=:" %%P in ('docker compose port app 8000') do set "WEB_PORT=%%P"
echo 启动完成：http://localhost:%WEB_PORT%
echo 查看日志：start-local.bat logs；停止并保留数据：start-local.bat stop
start "" "http://localhost:%WEB_PORT%"
exit /b 0

:stop_services
docker compose --profile demo down
if errorlevel 1 exit /b 1
echo 服务已停止；Fuseki 与 MQTT 数据卷已保留。
exit /b 0

:status_services
docker compose --profile demo ps -a
exit /b %errorlevel%

:logs_services
docker compose --profile demo logs --tail=100 -f app simulator
exit /b %errorlevel%

:failed
echo 启动失败。若是镜像拉取超时，请检查 Docker Desktop 的网络代理。
docker compose --profile demo ps -a
docker compose --profile demo logs --tail=60 app fuseki mqtt simulator
exit /b 1
