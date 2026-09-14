# ADR-0002 · Diario encadenado v1: especificación única

**Estado:** Aceptado · 2026-09-14 · Aaron Escobar

## Contexto
Hay tres definiciones incompatibles del diario:
- `libs/comun/diario.py`: JSON canónico en memoria, génesis `"0"*64`, tabla `diario_inmutable`.
- ARG-005 (`argos.journal_append`): `sha256(prev ‖ actor ‖ action ‖ subject::text)`, génesis `sha256('ARGOS-GENESIS')`, columnas `prev_hash`/`entry_hash`.
- ARG-066 (`verify_chain`): `sha256(prev ‖ actor ‖ action ‖ payload ‖ at)`, génesis de 32 bytes a cero, columnas `payload`/`hash`.

El verificador de ARG-066 marcaría como corruptas todas las filas escritas por ARG-005. Además, en ARG-005:
- La concatenación sin separadores es ambigua (`"ab"+"c"` = `"a"+"bc"`).
- `SELECT … ORDER BY seq DESC LIMIT 1 FOR UPDATE` no bloquea nada con la tabla vacía, y dos transacciones pueden encadenarse al mismo asiento previo (bifurcación).
- `GENERATED ALWAYS AS IDENTITY` deja huecos tras un rollback, que el verificador interpretaría como supresión.
- `SECURITY DEFINER` sin `search_path` fijo es secuestrable.
- El trigger no impide `TRUNCATE`.
- `jsonb::text` y `timestamptz::text` dependen de la normalización del motor.

## Decisión
Tabla `argos.audit_journal`:

| Columna | Tipo | Nota |
|---|---|---|
| `seq` | `bigint PRIMARY KEY` | contiguo desde 1, lo asigna `journal_append` (sin IDENTITY) |
| `at` | `timestamptz NOT NULL` | para consultas |
| `at_canon` | `text NOT NULL` | `YYYY-MM-DDTHH:MI:SS.ffffffZ` en UTC; **es lo que se hashea** |
| `actor` | `text NOT NULL` | `system:<servicio>` o `user:<sub>` |
| `action` | `text NOT NULL` | `dominio.verbo`, p. ej. `query.emit` |
| `payload` | `jsonb NOT NULL` | para consultas |
| `payload_canon` | `text NOT NULL` | JSON canónico; **es lo que se hashea** |
| `prev_hash` | `bytea NOT NULL` | 32 bytes |
| `entry_hash` | `bytea NOT NULL UNIQUE` | 32 bytes |

Hash de un asiento:
```
entry_hash = SHA-256( "ARGOS-JOURNAL-v1"
                      ‖ u64be(seq)
                      ‖ lp(at_canon) ‖ lp(actor) ‖ lp(action) ‖ lp(payload_canon)
                      ‖ prev_hash )
lp(x)  = u32be(longitud en bytes de UTF-8(x)) ‖ UTF-8(x)
génesis: prev_hash del asiento 1 = SHA-256("ARGOS-GENESIS")
```
JSON canónico: claves ordenadas, sin espacios (`,` y `:`), UTF-8 sin escapar, **sin números de coma flotante** (solo enteros, cadenas, booleanos, null, listas y objetos). Se valida al registrar.

Escritura: solo mediante `argos.journal_append(p_actor text, p_action text, p_payload_canon text) RETURNS bigint`, que:
- toma `pg_advisory_xact_lock`, lee la cabeza, calcula `seq`, `at_canon` y el hash en el propio motor, e inserta;
- se declara `SECURITY DEFINER SET search_path = pg_catalog, argos`.

Además, `INSERT` directo revocado a todos los roles de servicio, y triggers que prohíben `UPDATE`, `DELETE` (por fila) y `TRUNCATE` (por sentencia).

Verificación: implementación Python independiente (`libs/comun/diario.py`) que recalcula con la misma fórmula. Vectores de prueba compartidos en `tests/vectores/diario_v1.json`; los tests de Python y de PostgreSQL deben reproducirlos.

## Consecuencias
- ARG-012, ARG-066 y cualquier otro componente usan esta especificación; se abren Notas de Desviación ARG-005 y ARG-066.
- El anclaje de campaña (ARG-066) incluye `seq` y `entry_hash` de la cabeza.
- Cambiar la fórmula exige `ARGOS-JOURNAL-v2` y un asiento de transición; nunca reescribir.

## Alternativas descartadas
- Calcular el hash en Python e insertar: permite carreras entre procesos y confía el encadenado a cada cliente.
- `IDENTITY` para `seq`: huecos por rollback indistinguibles de supresiones.
- Hashear `jsonb::text` / `timestamptz::text`: depende de la versión y la configuración del motor.
