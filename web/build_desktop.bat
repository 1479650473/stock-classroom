@echo off
rem Desktop build: MSVC env + cargo tauri build (NSIS installer)
rem ASCII-only on purpose: cmd.exe default codepage garbles CJK in .bat
setlocal
pushd "%~dp0"
set "PATH=%USERPROFILE%\.cargo\bin;C:\nvm\v22.23.2;%PATH%"

call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
if errorlevel 1 (
  echo [build] vcvars64 VS18 failed, trying VS2019
  call "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
)

echo [build] dir=%CD%
node --version
cargo --version
where cl.exe

echo [build] start cargo tauri build
cargo tauri build --bundles nsis
echo [build] exit=%errorlevel%
popd
endlocal
