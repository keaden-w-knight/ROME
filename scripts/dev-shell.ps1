<#
.SYNOPSIS
    Puts the current PowerShell session into the MSVC x64 build environment.

.DESCRIPTION
    CMake with the Ninja generator expects cl.exe, the linker and the Windows
    SDK to already be on PATH; that is what vcvars64.bat sets up. This imports
    those variables into the running session, then makes two corrections that
    matter on this machine:

      * MSYS2 is removed from PATH. Its GCC toolchain shadows MSVC, and its
        Python (pulled in as a gdb dependency) shadows the python.org install
        the extension module has to be built against.

      * Python is pinned to an explicit interpreter, so which Python the build
        targets never depends on PATH ordering.

.EXAMPLE
    . .\scripts\dev-shell.ps1
    cmake --preset msvc-debug

.EXAMPLE
    .\scripts\dev-shell.ps1 -Run "cmake --build --preset msvc-debug"
#>
[CmdletBinding()]
param(
    # Python version the extension module is built for.
    [string]$PythonVersion = "3.13",

    # Optional command to run inside the configured environment. Without it,
    # dot-source this script to configure the current session instead.
    [string]$Run
)

$ErrorActionPreference = "Stop"

# --- Locate Visual Studio -------------------------------------------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "vswhere.exe not found. Is Visual Studio (or the Build Tools) installed?"
}

$vsPath = & $vswhere -products * `
    -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -latest -property installationPath
if (-not $vsPath) {
    throw "No Visual Studio installation with the x64 C++ toolset was found."
}

$vcvars = Join-Path $vsPath "VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path $vcvars)) {
    throw "vcvars64.bat not found at $vcvars"
}

# --- Import the developer environment -------------------------------------
# Run vcvars in cmd, dump the resulting environment, and replay it here.
cmd /c "`"$vcvars`" >nul 2>&1 && set" | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') {
        Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2]
    }
}

# --- Drop MSYS2 so it cannot shadow MSVC or the target Python -------------
$env:PATH = ($env:PATH -split ';' | Where-Object { $_ -and $_ -notmatch 'msys64' }) -join ';'

# --- Pin Python -----------------------------------------------------------
$pythonExe = & py "-$PythonVersion" -c "import sys; print(sys.executable)" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $pythonExe) {
    throw "Python $PythonVersion not found via the py launcher. Installed: $(& py -0p)"
}
$pythonDir = Split-Path $pythonExe -Parent

# Both the PATH entry and Python_ROOT_DIR are set: the first makes `python`
# work in the shell, the second is the hint CMake's FindPython honours.
$env:PATH = "$pythonDir;$pythonDir\Scripts;$env:PATH"
$env:Python_ROOT_DIR = $pythonDir

# --- Report ---------------------------------------------------------------
Write-Host "MSVC     : $((Get-Command cl).Source)"      -ForegroundColor Cyan
Write-Host "CMake    : $((Get-Command cmake).Source)"   -ForegroundColor Cyan
Write-Host "Ninja    : $((Get-Command ninja).Source)"   -ForegroundColor Cyan
Write-Host "Python   : $pythonExe"                      -ForegroundColor Cyan
Write-Host "Vulkan   : $env:VULKAN_SDK"                 -ForegroundColor Cyan

if ($Run) {
    Write-Host ""
    Write-Host "> $Run" -ForegroundColor DarkGray

    # Native tools in this build write progress to stderr (git clone, cl.exe,
    # ninja). Under PowerShell 5.1 that becomes a terminating NativeCommandError
    # while ErrorActionPreference is Stop, so the real exit code is what counts
    # here, not the stream.
    $ErrorActionPreference = "Continue"
    Invoke-Expression $Run
    exit $LASTEXITCODE
}
