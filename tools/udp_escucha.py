"""Muestra lo que AeroEscuela envía por UDP (Ajustes → Salida UDP). Uso:  python tools/udp_escucha.py [puerto]

Sirve para comprobar la conexión antes de enchufar un panel o una pantalla de instrumentos."""
import json
import socket
import sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 49020
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", port))
print(f"Escuchando en el puerto {port} (Ctrl+C para salir)…")
n = 0
while True:
    data, addr = sock.recvfrom(65535)
    d = json.loads(data.decode("utf-8"))
    n += 1
    if n % 10 == 1:
        avisos = ", ".join(k for k, v in d["avisos"].items() if v) or "ninguno"
        m = d["motores"][0]
        print(f"{addr[0]} · {d['estado']:10s} IAS {d['ias_kt']:5.0f} kt  ALT {d['alt_ind_ft']:6.0f} ft  "
              f"RUMBO {d['rumbo']:5.1f}  VS {d['vs_fpm']:+6.0f}  RPM {m['rpm']:5.0f}  avisos: {avisos}")
