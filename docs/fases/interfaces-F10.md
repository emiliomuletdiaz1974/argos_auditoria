# Interfaces que exporta la Fase 10 (estado real en main)

Generada a partir del código de `main` al cerrar la Fase 10 (tag `fase-10`). Los nombres de código están en inglés (ADR-0005).

- **Decisiones aplicables:**
  - ADR-0015 (operación sin appliance);
  - la nota de desviación `docs/desviaciones/ARG-091-100.md` (aprobada).

> **Probado en el entorno de desarrollo, no en el appliance.** La instalación en el equipo, la comprobación de sala medida y la alta disponibilidad en nodos reales esperan a F10-90, F10-91 y F10-92.

| Componente | Interfaz | Consumidores |
|---|---|---|
| ARG-091 | `platform/observability/objectives.yaml`; `tools/alert_rules.py` y `make alert-rules`; `platform/observability/rules/argos.rules.yml` (cada regla con `runbook_url`); Alertmanager con repetición horaria para las críticas | Operación, pantalla de operación, dossier |
| ARG-092 | `platform/observability/dashboards/{operation,compliance,ai-platform,logs}.json`, aprovisionados de solo lectura (`deploy/dev/grafana/dashboards.yaml`); los ocho semáforos de operación | Operación, consola |
| ARG-093 | `argos_common.logs.LokiHandler` (`ARGOS_LOKI_URL`, cola acotada, `loki_dropped()`); métrica `argos_log_records_dropped_total{service}`; Loki con retención de 720 h y el campo derivado `journal_seq` en Grafana | Todos los servicios, operación |
| ARG-094 | `argos_health` (`Monitor`, `measures`: `render_metrics`, `domain_observations`, `as_facts`, `publish_facts`); `/metrics` y `/facts`; `argos.health_facts` y `argos_facts.fresh()` (migraciones 0041 y 0042); rol `svc_health` | Prometheus, autoverificación, paneles |
| ARG-095 | `platform/ha/size-m/failover.py` y `rejoin.py` (`ComposeNodes`); perfil `ha` del compose; `platform/ha/size-l/patroni.yaml`; `docs/operacion/alta-disponibilidad.md` y RB-07 | Operación, F10-92 |
| ARG-096 | `argos_installer` (`InstallConfig`, `Step`, `STEPS`, `ORDER`, `Installer`); CLI `argos-install --config … [--dry-run] [--state-dir]`; informe `argos/installation/1` firmado; diario `install.completed`/`install.stopped`; tipo `installation` de la esclusa | Semana 1 del piloto, F10-90 |
| ARG-097 | `argos_installer.site_check` (`site_limits`, `prerequisites`, `measure`, `evaluate`); paso `site`; `argos-install --prerequisites S\|M\|L`; clave `site` de `platform/operation/sizes.yaml`; `tests/fixtures/site/` | Preventa, semana 1, F10-91 |
| ARG-098 | `argos_common.capacity` (`limits_of`, `measure`, `usage`, `enforce`, `take_snapshot`, `history`, `CapacityExceededError`); `platform/operation/sizes.yaml`; `POST /api/v1/systems` (`systems.create`, con segundo factor); `GET /api/v1/operations/capacity`; `argos.capacity_snapshots` (migración 0044) | API, consola, servicio de salud |
| ARG-099 | `docs/operacion/runbooks/RB-01…RB-12`; `tools/drill.py` (asiento `ops.drill`); `GET /api/v1/operations/status` y `/operations/runbooks/{id}` (`operations.read`); receptor `POST /internal/alertmanager` (migración 0043); vista «Operación» de la consola | Operador, organismo |
| ARG-100 | Retos `library/challenges/self/` (`self-001…012` y la trampa `self-099`); norma `SELF.ttl`; `argos_facts.facts` (migración 0040, rol `svc_selfcheck`); `tools/selfcheck.py` y `make selfcheck` (expediente firmado y puerta de release) | Release (F10-97), piloto |
| Documentación | `docs/operacion/`; modelo de amenazas 1.24 (M-41…M-46); dossier ENS 1.1 | Organismo, auditoría |
| Pruebas | `tests/e2e/test_phase10_acceptance.py`; `tests/observability/`; `tests/integration/test_{selfcheck,self_facts,health,operation_alerts,capacity,api_capacity,ha_size_m}.py`; `services/installer/tests/` | Piloto, auditoría |
