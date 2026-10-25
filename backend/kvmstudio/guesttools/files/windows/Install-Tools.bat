@echo off
rem KVM Studio guest tools for Windows: runs the virtio-win guest tools
rem installer (drivers, qemu-guest-agent, spice-vdagent) without questions.
rem The installer is on this CD, next to this script. /unattended: no pause.

setlocal
set WAIT=pause
if /i "%~1"=="/unattended" set WAIT=rem

net session >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set INSTALLER=%~dp0virtio-win-guest-tools.exe
if exist "%INSTALLER%" goto install
set INSTALLER=
for %%D in (D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
    if not defined INSTALLER if exist "%%D:\virtio-win-guest-tools.exe" set INSTALLER=%%D:\virtio-win-guest-tools.exe
)
if defined INSTALLER goto install
echo virtio-win-guest-tools.exe was not found on the KS_TOOLS CD nor on another drive.
echo Eject the CD from KVM Studio and insert it again.
%WAIT%
exit /b 2

:install
echo Installing the guest tools from %INSTALLER%, please wait...
start "" /wait "%INSTALLER%" /quiet /norestart
set CODE=%errorlevel%
echo.
if "%CODE%"=="0" goto done
if "%CODE%"=="3010" goto done
echo The installer failed with code %CODE%.
%WAIT%
exit /b %CODE%

:done
echo Guest tools installed. Copy and paste works after the next sign-in.
%WAIT%
exit /b 0
