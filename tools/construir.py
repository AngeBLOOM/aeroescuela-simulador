"""Construye el programa instalable de AeroEscuela para Windows.

    python tools/construir.py

1. Crea assets/icono.ico a partir de assets/icono.png.
2. Empaqueta con PyInstaller en dist/AeroEscuela/ (no hace falta Python en el equipo de destino).
3. Si está instalado Inno Setup 6, genera el instalador dist/AeroEscuela_Instalador.exe.
"""
import io
import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
VERSION = "1.3.0"


def make_ico(src="assets/icono.png", dst="assets/icono.ico"):
    import pygame
    pygame.init()
    img = pygame.image.load(src)
    entries = []
    for size in (256, 64, 48, 32, 16):
        im = pygame.transform.smoothscale(img, (size, size))
        buf = io.BytesIO()
        pygame.image.save(im, buf, "icono.png")
        entries.append((size, buf.getvalue()))
    head = struct.pack("<HHH", 0, 1, len(entries))
    off = 6 + 16 * len(entries)
    dirs, data = b"", b""
    for size, png in entries:
        dirs += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), off + len(data))
        data += png
    with open(dst, "wb") as f:
        f.write(head + dirs + data)
    print("icono:", dst)


def build():
    sep = ";"
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "AeroEscuela",
            "--icon", "assets/icono.ico", "--add-data", f"assets{sep}assets",
            "--collect-submodules", "winrt", "--collect-all", "glcontext",
            "--hidden-import", "comtypes.client", "--hidden-import", "comtypes.stream",
            "main.py"]
    print(" ".join(args))
    subprocess.check_call(args)
    # documentación junto al ejecutable
    for fn in ("LEEME.md", "docs/PROTOCOLO_ATC.md", "docs/GUIA_CABINA_FISICA.md"):
        shutil.copy(fn, os.path.join("dist", "AeroEscuela", os.path.basename(fn)))
    datos_iniciales()


# escenarios ya descargados que se instalan con el programa (funcionan sin Internet desde el primer arranque)
ESCENARIOS = ("SVBS", "SVFM")
CONFIG_INICIAL = {"ubicacion": "SVBS", "indicativo": "YV2026", "pantalla_instr": "ambiente", "fondo_instr": "futurista"}


def datos_iniciales():
    import json
    dst = os.path.join("dist", "AeroEscuela", "datos_iniciales")
    geo_dst = os.path.join(dst, "geo")
    os.makedirs(geo_dst, exist_ok=True)
    src = os.path.join("datos", "geo")
    files = ["airports.csv", "runways.csv", "navaids.csv", "airport-frequencies.csv"]
    for ident in ESCENARIOS:
        files += [f"loc2_{ident}.npz", f"feat_{ident}.npz", f"agua_{ident}.npz"]
    total = 0
    for fn in files:
        p = os.path.join(src, fn)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(geo_dst, fn))
            total += os.path.getsize(p)
        else:
            print("  (falta, se descargará en el primer uso):", fn)
    with open(os.path.join(dst, "config.json"), "w", encoding="utf-8") as f:
        json.dump(CONFIG_INICIAL, f, ensure_ascii=False, indent=1)
    print(f"datos iniciales: {len(files)} archivos, {total / 1e6:.0f} MB (escenarios {', '.join(ESCENARIOS)})")


ISS = r"""
#define MyApp "AeroEscuela"
[Setup]
AppId={{6E4F5A21-6B5C-4F2B-9A0D-AE5C0E5C1A01}
AppName=AeroEscuela
AppVersion=__VERSION__
AppPublisher=AeroEscuela
DefaultDirName={autopf}\AeroEscuela
DefaultGroupName=AeroEscuela
SourceDir=..
OutputDir=dist
OutputBaseFilename=AeroEscuela_Instalador
SetupIconFile=assets\icono.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\AeroEscuela\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AeroEscuela"; Filename: "{app}\AeroEscuela.exe"
Name: "{group}\Desinstalar AeroEscuela"; Filename: "{uninstallexe}"
Name: "{autodesktop}\AeroEscuela"; Filename: "{app}\AeroEscuela.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AeroEscuela.exe"; Description: "Abrir AeroEscuela ahora"; Flags: nowait postinstall skipifsilent
"""


def installer():
    cands = [os.path.expandvars(r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"),
             os.path.expandvars(r"%ProgramFiles%\Inno Setup 6\ISCC.exe"),
             os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe")]
    iscc = next((c for c in cands if os.path.exists(c)), None)
    with open("tools/instalador.iss", "w", encoding="utf-8") as f:
        f.write(ISS.replace("__VERSION__", VERSION))
    if iscc is None:
        print("Inno Setup no está instalado: el programa está listo en dist/AeroEscuela (se puede copiar tal cual).")
        return
    subprocess.check_call([iscc, "tools/instalador.iss"])
    print("Instalador: dist/AeroEscuela_Instalador.exe")


if __name__ == "__main__":
    make_ico()
    build()
    installer()
