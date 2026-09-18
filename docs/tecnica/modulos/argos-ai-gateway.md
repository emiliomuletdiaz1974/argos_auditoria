---
id: MOD-argos-ai-gateway
kind: module
title: Gateway de IA local (argos-ai-gateway)
module: argos-ai-gateway
phases: ["06"]
version: 0.1.0-alpha
commit: pendiente
date: 2026-09-17
status: draft
confidentiality: client
---

# Gateway de IA local (argos-ai-gateway)

## 1. Propósito

La capa de IA de ARGOS, entera dentro del perímetro del cliente: ni una llamada al exterior (P-03 del pliego). Es un **servicio auxiliar** con cuatro oficios —clasificar lo ambiguo, proponer retos desde texto normativo, redactar dictámenes y asistir en la consola— y dos prohibiciones que esta capa **implementa**, no declara: nunca decide conformidad y nunca ve datos del cliente en claro.

Implementa ARG-051 a ARG-060. En su estado actual contiene los guardarraíles (ARG-060); el resto llega en las tareas siguientes de la Fase 06, y este documento está en estado `draft` hasta entonces.

## 2. Alcance y límites

- **Hace:** depurar lo que entra a un prompt y vigilar lo que sale.
- **Hará:** colas, cuotas y JSON forzado (ARG-052), embeddings y RAG normativo (ARG-053, ARG-054), clasificación calibrada (ARG-055), generación de retos (ARG-056), dictámenes (ARG-057), asistente con herramientas (ARG-058) y el arnés de evaluación (ARG-059).
- **No hace, y no es una cuestión de configuración:** emitir un veredicto. No hay ruta de importación, ni de red, ni de permisos de base de datos que lleve de aquí al evaluador.
- **No hace:** escribir en un sistema del cliente, ni proponer que se escriba.

## 3. Arquitectura

- **`argos_ai.guardrails`** (ARG-060): `scrub_input` a la entrada y `check_output` a la salida. Puro, sin modelo y sin entrada/salida, para poder probarlo entero.
- Dependencias: `argos-common` (errores y configuración) y `argos-connector-sdk`, del que reutiliza los **validadores de identificadores españoles de ARG-024**.

### La barrera (F06-01)

Tres cierres, no una promesa escrita:

1. **Importaciones:** `tests/architecture/ai_boundary.py` sigue el grafo de importaciones real del espacio de trabajo y rechaza que cualquier módulo de este paquete alcance `argos_challenges.evaluator`, `.store` o `.findings`, aunque el cable esté atado tres módulos más allá.
2. **Permisos:** el rol `argos_ai` de PostgreSQL (migración `0015`) lee el esquema y escribe solo `argos.ai_usage`. Leer veredictos y hallazgos sí: redactar el informe desde ellos es el oficio de ARG-057.
3. **Red:** el contenedor no comparte red con la API de campañas (se comprueba en F06-13).

### Guardarraíles (ARG-060)

- **`scrub_input(text) -> (clean, substitutions)`.** Sustituye por marcadores estables (`[DNI-1]`, `[IBAN-1]`) lo que **valida** como identificador español, reutilizando `argos_connector.validators`. La diferencia con una expresión regular ciega es el producto: un código de producto con la forma de un DNI pero sin su letra de control se queda intacto. El mismo valor recibe el mismo marcador dentro de un texto, para no destrozar el sentido de la frase.
- **`check_output(answer) -> bool`.** Recorre todas las cadenas del JSON, por hondas que estén, y rechaza dos cosas con motivo tipificado:
  - `veredicto_no_citado`: una afirmación de conformidad sobre un activo sin el `verdict_id` del que sale;
  - `escritura_sobre_objetivo`: un verbo de escritura sobre un sistema.
- **Las tablas de patrones son contenido**, en `library/prompts/guardrails.yaml`, y el equipo las amplía sin una release. **La decisión de rechazar no es contenido:** no tiene interruptor.

## 4. Interfaces

| Función | Firma | Consumidores |
|---|---|---|
| `scrub_input` | `(text: str) -> tuple[str, int]` | ARG-052, toda inferencia |
| `check_output` | `(answer: Mapping[str, Any]) -> bool` | ARG-052, toda inferencia |
| `load_patterns` | `(path: Path = PATTERNS_FILE) -> dict[str, Any]` | ARG-052, telemetría |
| `OutputRejectedError` | excepción con el motivo | cada oficio la maneja: reintento con aviso o rehúso |

## 5. Configuración

`ARGOS_LLM_BASE_URL` y `ARGOS_LLM_MODEL` (ADR-0009), que aún no consume ningún módulo de este paquete. Los guardarraíles no necesitan configuración: sus tablas son contenido.

## 6. Seguridad y tratamiento de datos

- Ningún dato personal validado llega al modelo: se sustituye antes por un marcador.
- Ningún prompt se escribe en un log ni en una tabla; lo que se registra es su hash (ARG-052, `argos.ai_usage`).
- El paquete no puede escribir veredictos ni hallazgos, por código y por permisos.

## 7. Operación

El servicio aún no tiene contenedor propio; llega en F06-13, en su propia red.

## 8. Verificación

`services/ai-gateway/tests/test_guardrails_pure.py`: identificadores reales sustituidos y falsos intactos, marcador estable, conformidad sin veredicto rechazada y con veredicto permitida, verbos de escritura rechazados, texto anidado alcanzado y recomendación legítima no confundida con una orden.

`tests/architecture/test_ai_boundary.py` y `tests/integration/test_ai_boundary.py`: la barrera.

## 9. Limitaciones conocidas y pendientes

- El paquete está a medias: de los diez componentes solo está ARG-060.
- La telemetría de sustituciones se publica cuando exista el gateway (ARG-052).
- La lista de identificadores es la española de ARG-024; otro país necesita sus validadores, no otra expresión regular.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-17 | Guardarraíles de entrada y salida, con las tablas como contenido | Fase 06 (ARG-060) |
