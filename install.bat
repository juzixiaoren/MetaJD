@echo off
REM 安装依赖
TITLE Data Mining Environment Setup


echo.
echo =================================================================
echo.
rem 可修改此处以使用不同的环境名
set "env_name=datamining"

echo Activating Conda environment: %env_name%
echo.
echo =================================================================
echo.

REM 激活指定的Conda环境并执行安装命令
rem use script directory to find requirements.txt so it works when run from any cwd
set "REQ=%~dp0requirements.txt"

if not exist "%REQ%" (
    echo.
    echo ERROR: requirements file not found: "%REQ%"
    echo Please make sure "requirements.txt" is in the same folder as this script.
    echo.
    pause
    exit /b 1
)

rem Try activating the conda environment. This requires conda to be initialized for cmd.exe
call conda activate "%env_name%"
if errorlevel 1 (
    echo.
    echo ERROR: Failed to activate Conda environment "%env_name%".
    echo Make sure conda is installed and you have run:  conda init cmd.exe
    echo Then restart this command prompt and try again, or activate the environment manually:
    echo    conda activate %env_name%
    echo.
    pause
    exit /b 1
)

echo.
echo Environment '%env_name%' activated successfully.
echo.
echo Now installing dependencies from "%REQ%"...
echo.

rem Use python -m pip to ensure the pip from the activated environment is used
python -m pip install -r "%REQ%"
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed. Check the output above for details.
    echo You can try running: python -m pip install -r "%REQ%"
    echo.
    pause
    exit /b 1
)

echo.
echo =================================================================
echo.
echo Dependency installation process finished.
echo.
echo =================================================================
echo.

pause