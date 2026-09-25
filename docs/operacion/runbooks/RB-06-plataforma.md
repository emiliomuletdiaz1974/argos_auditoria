---
id: RB-06
title: "La plataforma: certificados y servicio de salud"
alerts: [CertificatesExpiring, HealthServiceDown]
confidentiality: client
---
# RB-06 · La plataforma: certificados y servicio de salud

## Síntoma

- `CertificatesExpiring`: algún servicio tiene su certificado interno a menos de 7 días de caducar. La rotación automática no lo ha renovado.
- `HealthServiceDown` (crítica): el servicio de salud no responde. Mientras dura, las alertas del diario, del WORM y del disco no pueden dispararse.

## Diagnóstico

1. **Certificados:** mira el semáforo «Certificados» y el estado del emisor interno:

```bash
docker compose -f deploy/dev/compose.yaml ps cert-issuer
curl http://127.0.0.1:8009/facts
```

2. **Servicio de salud:** comprueba si el contenedor está en marcha y por qué se paró:

```bash
docker compose -f deploy/dev/compose.yaml ps health
docker compose -f deploy/dev/compose.yaml logs health
```

## Acción

- **Certificados:** reinicia el emisor. Renueva lo que esté a menos de 10 días.
- **Servicio de salud:** reinícialo. Si no arranca, mira si le falta la credencial de Vault o la base de datos.

```bash
docker compose -f deploy/dev/compose.yaml restart cert-issuer
docker compose -f deploy/dev/compose.yaml restart health
```

## Verificación

- `argos_certs_expiring_7d` vuelve a 0.
- `up{job="argos-health"}` vuelve a 1 y los hechos de la autoverificación vuelven a ser recientes.

## Cuándo escalar

Si el emisor no renueva con Vault en marcha, o si el servicio de salud no arranca tras reiniciarlo: al soporte de ARGOS, con un paquete de diagnóstico.
