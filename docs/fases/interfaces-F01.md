# Interfaces que exporta la Fase 01 (estado real en main)

Generada a partir del código de `main` al cerrar la Fase 1 (tag `fase-01`). Los nombres de código están en inglés (ADR-0005); los documentos de fase se leen como especificación.

| Componente | Interfaz | Consumidores |
|---|---|---|
| ARG-001 | `argos_common.config`: `ArgosConfig`, `load_config()`, `get_config()`, `Environment`, `LogLevel`, `ApplianceSize`; campos `DATABASE_URL`, `NATS_URL`, `TEMPORAL_ADDRESS`, `OIDC_ISSUER`, `OIDC_AUDIENCE`, `WORM_STORAGE_PATH`, `LOG_LEVEL`, `LOG_FORMAT_JSON`, `LLM_LOCAL_ENDPOINT` (variables `ARGOS_*`) | Todos los servicios |
| ARG-001 | `argos_common.logs`: `configure_logging(service, level, stream)`, `get_logger(name, component)`; campos obligatorios `timestamp`, `level`, `service`, `component`, `logger`, `message`; opcionales `journal_seq`, `trace_id`, `campaign_id` | Todos; Loki (ARG-093) |
| ARG-001 | `argos_common.errors`: `ArgosError(message, code, details)`, `ConfigurationError`, `IntegrityError`, `ReadOnlyViolationError`, `SecretNotAccessibleError` | Todos |
| ARG-001 | `argos_common.health.mount_health(app, service, version, checks, timeout)`; `GET /health` (200/503, `status` ok/degraded, `checks` ok/fail) y `GET /health/live` | Todos los servicios HTTP; F10 |
| ARG-001 | `argos_common.ids.uuid7()` | Esquema núcleo, eventos, F2+ |
| ARG-004/005 | PostgreSQL 16 + AGE + pgvector: esquema `argos` (`schema_version`, `settings`, `systems`, `campaigns`, `audit_journal`); `argos.journal_append(actor, action, payload_canon) → seq`; `argos.journal_hash(...)`; triggers que prohíben UPDATE, DELETE y TRUNCATE | Todas las fases |
| ARG-005 | `argos_common.journal`: `compute_hash`, `canonicalize`, `verify_entries`, `require_integrity`, `JournalEntry`, `VerificationResult`, `Anomaly`, `GENESIS`; `argos_common.journal_pg.PostgresJournal(dsn)`: `append(actor, action, payload, conn=None)`, `read(from_seq, to_seq)`, `verify(from_seq, to_seq)`, `head()` | ARG-012 (en la transacción del conector), ARG-066 (anclaje) |
| ARG-005 | `argos_common.migrations.apply_migrations(dsn, directory)`, `list_migrations`, `checksum`; `tools/migrate.py` | Todas las fases con migraciones |
| ARG-006 | `argos_events`: `Bus(service, url, journal=None, retry_delay, max_deliveries)` con `connect`, `close`, `publish(subject, event_type, data, audit=False)` y `subscribe(subject, durable, handler)`; `envelope`, `ensure_streams`, `STREAMS` (DISCOVERY 30 d, CHALLENGE 90 d, EVIDENCE 50 GB) | Fases 2–8 |
| ARG-007 | `argos_challenges.worker`: `TASK_QUEUE = "argos-campaigns"`, `create_worker(client, task_queue)`; `argos_challenges.workflows.RETRY_POLICY`; patrón workflow sin E/S + actividades; actividad `record_in_journal(action, payload)` | Fase 5 (ARG-043…049), Fase 10 |
| ARG-008 | Realm `argos` (roles `platform_admin`, `campaign_manager`, `dpo_reviewer`, `read_only_auditor`; clientes `argos-console` y `argos-api`); `argos_auth.validate(token, required_role)` y `JwtValidator(issuer, audience, keys)` → `Identity(sub, name, roles)` con `actor` | Fase 8 (API y consola), ARG-047 |
| ARG-009 | `argos_common.secret_stores`: `SecretStore`, `VaultSecretStore(url, token, mount)`, `EncryptedFileSecretStore`, `TpmSecretStore` (pendiente ARG-082); Vault `argos/services/<svc>`, `argos/connectors/<id>` (solo `svc-connector-sdk`), `pki_int/roles/argos-svc` | Fase 2 (SDK de conectores), ARG-083, ARG-064 |
| ARG-010 | `argos_common.release`: `build_manifest`, `serialize`, `Signer`, `VaultTransitSigner`, `verify_signature`; `tools/release.py build|sign|verify`; `dist/release-manifest.json` + `.sig` + `release.pub`; `make build` y `make manifest`; etapas CI `build`, `package`, `sign` y `selfcheck` | ARG-086, ARG-087, ARG-100 |
| ARG-002/003 | Aplazados (Nota de Desviación ARG-002-003, tarea F1-11) | — |

## Entorno de desarrollo (`make dev`)

PostgreSQL `127.0.0.1:55432` · NATS `4222` · Temporal `7233` · Keycloak `8180` · Vault `8200` · Prometheus `9090` · Loki `3100` · Grafana `3000` · servicio de ejemplo `8001`.
