---
id: MOD-argos-events
kind: module
title: Bus de eventos (argos-events)
module: argos-events
phases: ["01"]
version: 0.1.0-alpha
commit: 1aadd28
date: 2026-09-17
status: current
confidentiality: client
---

# Bus de eventos (argos-events)

## 1. Propósito

Publicación y consumo de eventos entre los servicios de ARGOS sobre NATS JetStream, con formato CloudEvents 1.0. Ningún servicio habla con NATS directamente: todos usan esta librería. Implementa ARG-006.

## 2. Alcance y límites

- Transporta hechos internos de la plataforma (descubrimiento, retos, campañas, punteros a evidencia).
- No transporta la evidencia en sí: el stream de evidencia solo lleva punteros a artefactos sellados.
- No conecta con sistemas del cliente.

## 3. Arquitectura

- **Clase `Bus`:** conexión, publicación y suscripción duradera.
- **Función `envelope`:** construye el sobre CloudEvents con id UUID v7, origen `//argos/<servicio>`, tipo `eu.argos.<dominio>.<evento>.vN` y marca de tiempo UTC.
- **Streams**, que `ensure_streams` crea o actualiza al conectar:

| Stream | Sujetos | Retención |
|---|---|---|
| `DISCOVERY` | `argos.discovery.>` | 30 días |
| `CHALLENGE` | `argos.challenge.>`, `argos.campaign.>` | 90 días |
| `EVIDENCE` | `argos.evidence.>` | acotada por tamaño (50 GB) |

Dependencias: `argos-common` (identificadores, diario y registro) y `nats-py`.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Clase | `Bus(service, url, journal=None, retry_delay=30.0, max_deliveries=5)` | Cliente del bus de un servicio |
| Método | `connect()`, `close()` | Abre la conexión y asegura los streams; cierre ordenado con drenaje |
| Método | `publish(subject, event_type, data, audit=False)` | Valida sujeto y tipo, publica y devuelve la secuencia confirmada |
| Método | `subscribe(subject, durable, handler)` | Consumidor duradero con confirmación manual |
| Función | `envelope(service, event_type, data)` | Sobre CloudEvents |
| Constante | `STREAMS` | Configuración de los tres streams |

## 5. Configuración

- `ARGOS_NATS_URL` (desde `argos-common`).
- Por servicio: `retry_delay` (espera antes de reintentar) y `max_deliveries` (entregas máximas por mensaje).

## 6. Seguridad y tratamiento de datos

- Sujetos y tipos se validan con patrones cerrados (`argos.<dominio>.<evento>`, `dominio.evento.vN`); se rechaza cualquier otro valor.
- **Publicación auditada** (`audit=True`): el asiento `event.publish` se escribe en el diario **antes** de publicar, así queda constancia aunque la publicación falle después.
- Un mensaje malformado se descarta definitivamente y se registra sin su contenido.
- Si el manejador falla, el mensaje se reintenta tras `retry_delay`, hasta `max_deliveries` entregas.
- Decisiones aplicables: ADR-0005 (nombres en inglés).

## 7. Operación

- NATS con JetStream y almacenamiento en fichero; en desarrollo, en `127.0.0.1:4222` con monitorización en `8222`.
- Los consumidores duraderos sobreviven a reinicios del servicio y retoman donde lo dejaron.

## 8. Verificación

- **Test unitario:** `libs/events/tests/test_envelope.py` (formato del sobre y validaciones).
- **Test de integración:** `tests/integration/test_nats_bus.py` (publicación, suscripción duradera, reintentos y publicación auditada contra NATS real).

## 9. Limitaciones conocidas y pendientes

- Réplica 1 por stream: la alta disponibilidad de NATS corresponde al despliegue del appliance (Fase 10).

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-14 | Librería de eventos con CloudEvents, reintentos acotados y auditoría opcional | Fase 01 (ARG-006) |
