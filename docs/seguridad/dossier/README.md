# Dossier de seguridad v1 · ENS categoría media e ISO/IEC 27001:2022

**Versión:** 1.0 · **Fecha:** 2026-09-24 · **Tarea:** F09-16 · **Confidencialidad:** `client`

Paquete que el organismo incluye en su declaración de aplicabilidad y que la consultora usa en el proceso de certificación.

- **Qué recoge:** cada medida del Anexo II del Real Decreto 311/2022 y cada control del Anexo A de la ISO/IEC 27001:2022, con su estado y el enlace a su evidencia en el repositorio.
- **Qué decide el organismo:** la aplicabilidad final de cada medida a su sistema. Esa decisión va en su propia Declaración de Aplicabilidad.

| Documento | Qué es |
|---|---|
| [Descripción del sistema](00-descripcion-sistema.md) | Arquitectura, flujos de datos y fronteras de confianza |
| [Medidas del ENS](ens-medidas.md) | Las 73 medidas del Anexo II, con estado y evidencia |
| [Controles del Anexo A de la ISO/IEC 27001](iso27001-anexo-a.md) | Los 93 controles, con su medida ENS equivalente |
| [SBOM](sbom/README.md) | Lista de materiales de la última release y su informe de vulnerabilidades |
| [Modelo de amenazas](../modelo-amenazas.md) | Activos, adversarios, superficies y mitigaciones |
| [Revisión de seguridad de F1–F8](../revision-f01-f08.md) | Hallazgos tratados como los de un cliente, con su corrección |
| [Batería de accesos indebidos](../bateria-accesos.md) | Informe generado contra la API desplegada |
| [Backup y restauración probada](../backup-restauracion.md) | Qué se copia y cómo se prueba la restauración; la última prueba queda en `argos.restore_tests` |
| [Endurecimiento de la imagen](../endurecimiento-imagen.md) | CIS Level 1 y sellado del disco al TPM |

## Estados

| Estado | Significa |
|---|---|
| `implementada` | Está en el código o en el proceso de desarrollo del producto, igual en cualquier despliegue, y un test o un informe lo demuestra |
| `implementada en desarrollo` | Depende de la configuración del despliegue y se ha probado en el entorno de desarrollo (Docker Compose), todavía no en el appliance |
| `pendiente de hardware` | Necesita el equipo físico (TPM, Secure Boot, imagen endurecida o k3s); cita la tarea que lo hará |
| `responsabilidad del organismo` | Es una medida organizativa, física o de personal del organismo que opera el appliance; el producto puede aportar evidencia, pero no la cumple por sí mismo |

`tests/docs/test_security_dossier.py` comprueba en cada ejecución que:

- están todas las medidas y todos los controles;
- ningún estado se sale de estos cuatro;
- lo implementado enlaza a una ruta que existe;
- nada se presenta como implementado con evidencia que solo existe en el compose de desarrollo;
- lo pendiente de hardware cita su tarea manual.

## Empaquetado para un organismo

```
uv run python tools/docs_pack.py --security --label <organismo>
```

Genera en `dist/documentacion/`:

- este dossier y los documentos de seguridad en Markdown y PDF;
- los SBOM de `dist/sbom/`, si se han generado con `make sbom`;
- un índice y un manifiesto con el SHA-256 de cada fichero.

Solo entran los documentos `client`, salvo que se pida lo contrario de forma expresa.
