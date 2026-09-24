# SBOM de la release

**Versión:** 1.0 · **Fecha:** 2026-09-24 · **Confidencialidad:** `client`

Los SBOM no se versionan en el repositorio: se generan para cada release, en formato CycloneDX, junto con el informe de vulnerabilidades de cada imagen.

```
make sbom
```

`tools/sbom.py` y `tools/vuln_gate.py`, con syft y grype fijados por digest, dejan en `dist/sbom/`:

- `<imagen>.cdx.json`: la lista de materiales de cada imagen del appliance y de la consola;
- `<imagen>.vulns.json`: el informe de vulnerabilidades de grype sobre ese SBOM.

**La puerta de vulnerabilidades** falla la release en dos casos:

- una vulnerabilidad crítica con corrección publicada;
- una alta cuya corrección tiene más de 30 días.

Las excepciones, con justificación, autor y caducidad, están en `platform/security/vex.yaml`.

**Cómo llegan al organismo:**

- El manifiesto de release firmado lleva el SHA-256 de cada SBOM y de cada informe. El actualizador los comprueba antes de aplicar nada (ARG-087).
- `tools/docs_pack.py --security` copia al paquete del dossier los SBOM que haya en `dist/sbom/`, con su huella en el manifiesto del paquete.
