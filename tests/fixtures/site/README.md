# Salidas de referencia de la comprobación de sala (F10-11)

- **Capturadas** en un contenedor `debian:bookworm-slim` el 2026-09-25: `ping_ok.txt` (`ping -c 10 -i 0.2 -q 127.0.0.1`), `ping_unreachable.txt` (`ping -c 3 -W 1 -q 10.255.255.1`) y `ethtool_10g.txt` (`ethtool eth0`).
- **Escritas con el formato documentado**, porque aún no hay hardware:
  - `ethtool_down.txt`: enlace caído;
  - `ipmitool_sensor_list*.txt`: `ipmitool sensor list`;
  - `nvidia_smi_*.txt`: `nvidia-smi --query-gpu=name,memory.total --format=csv`.

  Se sustituyen por capturas del equipo real en F10-91.
