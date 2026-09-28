---
id: MOD-argos-health
kind: module
title: Servicio de salud del dominio (argos-health)
module: argos-health
phases: ["10"]
version: 0.7.0-alpha
commit: 614dfaf
date: 2026-09-28
status: current
confidentiality: client
---

# Servicio de salud del dominio (argos-health)

## 1. Propósito

Mide lo que ningún exporter estándar sabe medir de ARGOS:

- si el diario de auditoría y el registro de seguridad verifican su cadena;
- si el almacén WORM guarda y devuelve lo que se le da;
- cuántas campañas hay en marcha, cuántas horas lleva una compuerta sin aprobar y qué cortacircuitos están abiertos;
- cuánto espera cada cola (sellado, webhooks y revisión) y si alguna está atascada;
- cuánto ocupa el volumen de evidencia;
- si algún certificado interno caduca en los próximos 7 días;
- cuándo terminó bien por última vez cada trabajo periódico (copia, prueba de restauración, calibración y reexploración).

Lo publica en `/metrics` para Prometheus y en `/facts` en JSON. Además deja en la base los hechos que solo él observa, para que los retos `self-*` de la autoverificación los lean. Implementa ARG-094 (tarea F10-02; ADR-0015, punto 2; nota de desviación ARG-091-100).

## 2. Alcance y límites

- **Qué hace:** mide y publica. Lee lo que mide y solo escribe sus propios hechos.
- **Qué no hace:**
  - no decide alertas: eso son las reglas de `platform/observability/` y Alertmanager (F10-03);
  - no repara nada;
  - no mide la salud de los procesos, que ya da `/health` de cada servicio.
- **Verificaciones:** el diario y el registro de seguridad se verifican con sus propios verificadores (`PostgresJournal.verify` y `security_log.verify_chain`), nunca con una cadena reimplementada aquí.

## 3. Arquitectura

- **`measures`:** cada medida como una función sobre su fuente:
  - `worm_canary`: escribe un objeto de pocos bytes con retención de un día en `health/canary/`, lo relee y compara; nunca lanza;
  - `journal_ok`: el último tramo (10 000 asientos) o la cadena entera;
  - `security_log_ok`;
  - `domain_observations`: campañas, colas, compuertas, cortacircuitos, trabajos y colas atascadas, con los estados reales de las tablas;
  - `certificates_expiring`: cuenta solo el certificado más nuevo de cada nombre, porque el emisor renueva a los dos tercios de su vida y el viejo sigue existiendo un tiempo;
  - `render_metrics`: el formato de texto de Prometheus.
- **`monitor.Monitor`:** guarda la última observación de cada comprobación. Una comprobación que falla deja su indicador a 0 y lo anota en el log, así que una fuente rota se ve como un valor malo, nunca como uno bueno envejecido.
- **`app`:** FastAPI. Al arrancar hace una ronda completa y después cada comprobación sigue su cadencia:

| Comprobación | Cadencia |
|---|---|
| Tramo del diario y registro de seguridad | 5 minutos |
| Diario entero | 24 horas |
| Canario WORM, recuentos del dominio y volumen | 30 segundos |
| Certificados | 1 hora |

  Tras cada ronda publica sus hechos en `argos.health_facts`.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| HTTP | `GET /metrics` | Texto de Prometheus (lo que se enumera abajo) |
| HTTP | `GET /facts` | `{"facts": {...}, "measures": {...}}` |
| HTTP | `GET /health/live`, `/health/ready` | Salud del proceso, como el resto de servicios |
| Tabla | `argos.health_facts(fact, setting, observed_at)` | `journal_intact`, `security_log_intact`, `worm_healthy`, `certs_expiring_7d`, `queues_stalled` (migración 0041) |
| Vista | `argos_facts.facts` | La lee la autoverificación. Los hechos del servicio solo valen si tienen menos de 15 minutos (`argos_facts.fresh`) |

Métricas:

- `argos_journal_verify_ok{scope="tail"|"full"}`;
- `argos_security_log_verify_ok`;
- `argos_worm_healthy`;
- `argos_campaigns_running`;
- `argos_campaign_gate_waiting_hours{campaign,gate}`;
- `argos_connector_circuit_open{system}`;
- `argos_tsa_queue_pending`, `argos_webhook_deliveries_pending` y `argos_review_queue_pending`;
- `argos_evidence_volume_used_ratio`;
- `argos_certs_expiring_7d` (-1 si no se pudo medir);
- `argos_job_last_success_timestamp_seconds{job}` (0 si nunca);
- `argos_scan_last_duration_seconds{system}`: cuánto duró la última exploración completada de cada sistema (objetivo de reexploración por debajo de 2 horas, §3.10);
- `argos_health_check_timestamp_seconds{check}`;
- para los paneles de F10-04, siempre como agregados:
  - `argos_build_info{version}`: la release, leída del fichero `VERSION` de la imagen;
  - `argos_campaigns_total{status}` y `argos_findings_open{severity}`, con todos los estados y severidades aunque valgan 0;
  - `argos_findings_remediation_hours`: mediana de horas hasta la subsanación verificada en 90 días;
  - `argos_inventory_coverage_ratio{system}`;
  - `argos_ai_tokens_24h`, `argos_ai_requests_24h`, `argos_ai_latency_p95_ms` y `argos_ai_quota_used_ratio`, por servicio;
  - `argos_ai_calibration_age_hours{category}`;
- `argos_log_records_dropped_total{service}`: líneas de log que el servicio no pudo enviar a Loki (F10-05).
- `argos_health_check_ok{check}`: 1 si la última pasada de una comprobación pudo medir y 0 si no (fallo de la consulta, PKI o volumen sin configurar, almacén WORM ausente). La vigila `HealthCheckFailing`: una comprobación que no mide deja sus alertas mudas (QA-079).
- **Hechos con su propia hora (QA-078):** cada hecho se publica en `argos.health_facts` con la hora de la comprobación que lo observó, no con la de la publicación. Si una comprobación se cuelga, su hecho envejece y `argos_facts.fresh` deja de fiarse de él a los 15 minutos.

Además, una vez al día toma la foto de la capacidad frente a la talla (`argos.capacity_snapshots`, F10-08) y borra lo que tenga más de 13 meses.

## 5. Configuración

| Variable | Qué es | Por defecto |
|---|---|---|
| `ARGOS_DATABASE_URL`, `ARGOS_DATABASE_VAULT_ROLE`, `ARGOS_VAULT_APPROLE_DIR` | Base de datos con usuario dinámico `svc-health` (F09-05) | — |
| `ARGOS_HEALTH_S3_ENDPOINT`, `_S3_ACCESS_KEY`, `_S3_SECRET_KEY` | Almacén WORM del canario; sin endpoint, el canario da 0 | — |
| `ARGOS_HEALTH_PKI_URL` | PKI intermedia de Vault (`…/v1/pki_int`); sin ella, los certificados dan -1 | — |
| `ARGOS_HEALTH_TLS_SERVICES` | Los servicios que renueva el emisor de certificados, con el mismo formato que su `ARGOS_TLS_SERVICES`; solo cuentan sus certificados, y uno que falte cuenta como a punto de caducar (QA-088). Un test comprueba que el compose da a los dos el mismo valor | vacío: cuentan todos |
| `ARGOS_HEALTH_EVIDENCE_PATH` | Volumen de evidencia montado en solo lectura; sin él no hay métrica de ocupación | — |
| `ARGOS_HEALTH_JOURNAL_TAIL` | Asientos del tramo | 10 000 |
| `ARGOS_HEALTH_*_SECONDS` | Cadencias | las de la tabla del punto 3 |

## 6. Seguridad y tratamiento de datos

- **Eventos agotados (QA-001):** `argos_events_dead_letters` cuenta los eventos guardados en `argos.event_dead_letters` sin resolver, y `EventsDeadLettered` avisa (migración 0045).
- **Base de datos:** el rol `svc_health` solo lee las tablas que mide (desde la migración 0042, también hallazgos, cobertura y uso de la IA) y solo escribe en `argos.health_facts`. De la IA solo cuenta tokens, peticiones y duraciones: nunca lee un prompt ni su huella. No puede escribir en el diario ni leer veredictos (matriz `db_access_matrix.yaml`).
- **Vault:** su AppRole lee su credencial de base de datos, lista `pki_int/certs` y lee `pki_int/cert/*`. Los certificados son públicos, pero Vault pide un token para listarlos.
- **Contenedor:** tiene la postura de F09-03 y su propio certificado del emisor interno. Monta el volumen de evidencia en **solo lectura**, y solo para medir su ocupación.
- **Canario:** son objetos de pocos bytes sin datos, en `health/canary/`, con retención de un día.
- **Datos:** las métricas no llevan datos personales. Las etiquetas son nombres de sistemas, identificadores de campaña y nombres de trabajos.

## 7. Operación

- En desarrollo es el servicio `health` del compose, con el puerto `127.0.0.1:8009` en el anfitrión. Prometheus lo recoge con el trabajo `argos-health`.
- Si deja de mirar, los hechos de la autoverificación se vuelven falsos a los 15 minutos, y la release queda bloqueada. Un monitor callado no se lee como un appliance sano.

## 8. Verificación

- `services/health/tests/test_health_pure.py`:
  - canario correcto, corrupto e inaccesible;
  - tramo del diario;
  - certificados renovados frente a los que caducan;
  - formato de las métricas;
  - hechos del diario.
- `tests/integration/test_health.py`:
  - todas las métricas sobre una base desechable;
  - el diario roto da 0;
  - los hechos llegan a la vista mientras son frescos;
  - los permisos del rol.
- `tests/integration/test_self_facts.py` y `test_selfcheck.py`: la autoverificación lee lo que el monitor publica.
- `tests/integration/test_container_posture.py` y `test_service_roles.py` incluyen el contenedor y su rol.

## 9. Limitaciones conocidas y pendientes

- Los canarios caducan a un día, pero el cliente WORM no borra (ARG-061). Hace falta una regla de ciclo de vida del almacén que los retire.
- El canario usa la misma cuenta S3 que el servicio de evidencia. Una cuenta propia, limitada a `health/canary/`, queda para el appliance.
- La ocupación del volumen solo se mide donde el volumen es visible: en el compose, montándolo en solo lectura.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-24 | Primera versión | F10-02 (ARG-094) |
| 0.2.0-alpha | 2026-09-24 | Duración de la última exploración por sistema, para la alerta `ScanTooSlow` | F10-03 (ARG-091) |
| 0.3.0-alpha | 2026-09-24 | Versión, campañas, hallazgos, cobertura e IA para los paneles (migración 0042) | F10-04 (ARG-092) |
| 0.4.0-alpha | 2026-09-24 | Líneas de log descartadas antes de llegar a Loki | F10-05 (ARG-093) |
| 0.5.0-alpha | 2026-09-25 | Foto diaria de la capacidad frente a la talla | F10-08 (ARG-098) |
| 0.6.0-alpha | 2026-09-28 | `argos_health_check_ok` y su alerta, hechos con la hora de su comprobación, y certificados solo de los servicios esperados | QA-22 (QA-078, 079, 088) |
| 0.7.0-alpha | 2026-09-28 | `argos_events_dead_letters` y la alerta `EventsDeadLettered` | QA-25 (QA-001) |
