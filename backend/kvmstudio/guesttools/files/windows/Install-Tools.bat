@echo off
rem KVM Studio guest tools for Windows: runs the virtio-win guest tools
rem installer (drivers, qemu-guest-agent, spice-vdagent) without questions.

net session >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set INSTALLER=
for %%D in (D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
    if exist "%%D:\virtio-win-guest-tools.exe" set INSTALLER=%%D:\virtio-win-guest-tools.exe
)
if not defined INSTALLER (
    echo The virtio-win disc was not found. Insert it again from KVM Studio.
    pause
    exit /b 1
)

echo Installing the guest tools, please wait...
start "" /wait "%INSTALLER%" /quiet /norestart
echo.
echo Guest tools installed. Copy and paste works after the next sign-in.
pause
