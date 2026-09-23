# Registro de decisiones de ARGOS

**Confidencialidad:** `internal` · **Última revisión:** 2026-09-23 (hasta F09-00)

Aquí está en un solo sitio **qué hemos decidido, por qué y qué comprobamos antes de decidirlo**. Las fuentes son los ADR (`docs/adr/`), las notas de desviación (`docs/desviaciones/`) y la bitácora del plan. Cada entrada remite a su documento original, que sigue siendo el que manda.

## Cómo consultarlo

| Busco… | Voy a |
|---|---|
| Una decisión concreta en una línea | [Índice rápido](#índice-rápido) (abajo) |
| Por qué elegimos una tecnología o una arquitectura | [01 · Arquitectura (ADR)](01-arquitectura.md) |
| Por qué no hicimos lo que decía un documento de fase | [02 · Desviaciones](02-desviaciones.md) |
| Alcance, orden del plan, reglas de trabajo y decisiones tomadas dentro de las tareas | [03 · Plan y proceso](03-plan-y-proceso.md) |
| Qué incoherencias encontramos en la documentación y qué hicimos con ellas | [04 · Revisión del 2026-09-23](04-revision-2026-09-23.md) |

## Cómo decidimos

1. **Primero comprobamos el terreno.** Antes de cada fase leemos el documento de fase entero, el Plan Director, el Pliego y lo que ya está construido. Además probamos con sondas las librerías y las imágenes (versiones reales, qué falla y qué no). Lo que chocaba con la realidad se anotó con su prueba.
2. **Quién manda en qué.** Los documentos de fase mandan en qué se construye y en las rutas. El Plan Director manda en el orden y en la definición de hecho. **Un ADR manda sobre ambos**, y apartarse de un documento exige antes una nota de desviación.
3. **Las decisiones de peso pasan por una tarea DECISIÓN** (`E0-03`, `F04-00`, `F05-00`, `F06-00`, `F07-00`, `F08-00`, `F09-00`). En ella se proponen opciones con recomendación, se elige y el ADR pasa a «Aceptado».
4. **Las decisiones pequeñas se toman dentro de la tarea** y quedan escritas en la bitácora con su motivo. Las que cambian una interfaz o se apartan del documento se suben a una nota de desviación.
5. **Mantenimiento:** toda decisión nueva se añade a este registro en el mismo commit que la aplica.

## Índice rápido

Leyenda del **Quién**: **U** = decisión nuestra en una tarea DECISIÓN o por indicación directa · **T** = tomada dentro de una tarea con su motivo escrito.

### Arquitectura y herramientas

| ID | Fecha | Quién | Decisión | Ficha |
|---|---|---|---|---|
| ADR-0001 | 2026-09-14 | U | Los documentos de fase mandan en qué y dónde; el Plan Director, en orden y método. Packer y k3s esperan al hardware y mientras usamos Docker Compose | [→](01-arquitectura.md#adr-0001) |
| ADR-0002 | 2026-09-14 | U | Diario encadenado v1: hash con prefijo de longitud, `seq` sin huecos bajo bloqueo, escritura solo por `journal_append` | [→](01-arquitectura.md#adr-0002) |
| ADR-0003 | 2026-09-14 | U | uv, ruff, mypy estricto, pytest y gitleaks; CI en GitHub Actions | [→](01-arquitectura.md#adr-0003) |
| ADR-0004 | 2026-09-14 | U | La web parte de la v7_1 (trae el bloque legal) y no de la v6 | [→](01-arquitectura.md#adr-0004) |
| ADR-0005 | 2026-09-14 | U | Código en inglés; documentación y git en español | [→](01-arquitectura.md#adr-0005) |
| ADR-0006 | 2026-09-16 | U | Ontología con rdflib en proceso, pySHACL, OPA en servidor y bundles firmados con Ed25519; capa de traducción para el jurista | [→](01-arquitectura.md#adr-0006) |
| ADR-0007 | 2026-09-17 | U | DSL de retos en YAML con JSON Schema, veredicto de 4 valores, evaluador puro, campaña sobre instantánea y sello en la F05 | [→](01-arquitectura.md#adr-0007) |
| ADR-0008 | 2026-09-17 | U | Sujeto sintético: ARGOS genera y registra, el cliente inyecta y ejercita; ARGOS nunca escribe | [→](01-arquitectura.md#adr-0008) |
| ADR-0009 | 2026-09-17 | U | Qwen2.5-14B y e5-small; llama.cpp en CPU en desarrollo; los tests no dependen del modelo | [→](01-arquitectura.md#adr-0009) |
| ADR-0010 | 2026-09-18 | U | Evidencia en VersityGW con object lock en conformidad, probado con un test; nunca AGPL | [→](01-arquitectura.md#adr-0010) |
| ADR-0011 | 2026-09-18 | U | Credencial VC 2.0 `eddsa-jcs-2022`, `did:web` y Bitstring Status List | [→](01-arquitectura.md#adr-0011) |
| ADR-0012 | 2026-09-20 | U | Una sola API autenticada `/api/v1`; se retira `challenge-api` | [→](01-arquitectura.md#adr-0012) |
| ADR-0013 | 2026-09-20 | U | Consola en React + Vite + TypeScript estricto, con tipos generados del contrato | [→](01-arquitectura.md#adr-0013) |
| ADR-0014 | 2026-09-23 | U | Seguridad en tres niveles (compose ya, estático ya, hardware después); roles de base de datos por servicio, mTLS, MFA y registro de seguridad propio | [→](01-arquitectura.md#adr-0014) |

### Alcance, plan y forma de trabajar

| ID | Fecha | Quién | Decisión | Ficha |
|---|---|---|---|---|
| DP-01 | 2026-09-14 | U | Aceptamos las cuatro recomendaciones de E0-03 (ADR 0001–0004) | [→](03-plan-y-proceso.md#dp-01) |
| DP-02 | 2026-09-14 | U | La publicación de la web (W-09) queda fuera de este plan | [→](03-plan-y-proceso.md#dp-02) |
| DP-03 | 2026-09-14 | U | Todo el código pasa a inglés y se refactoriza lo ya hecho (R-01, R-02) | [→](03-plan-y-proceso.md#dp-03) |
| DP-04 | 2026-09-16 | U | Validación jurídica de la Fase 04 retenida hasta tener perfil jurídico; el trabajo no se para | [→](03-plan-y-proceso.md#dp-04) |
| DP-05 | 2026-09-16 | U | El rendimiento del grafo se ataca ya (F03-15) y se acepta el criterio reformulado | [→](03-plan-y-proceso.md#dp-05) |
| DP-06 | 2026-09-17 | U | Documentación técnica para clientes antes de seguir (etapa D), con PDF y confidencialidad por documento | [→](03-plan-y-proceso.md#dp-06) |
| DP-07 | 2026-09-17 | U | Fase 04: verdad terreno provisional, mejoras del clasificador y cierre técnico `fase-04-tecnica` | [→](03-plan-y-proceso.md#dp-07) |
| DP-08 | 2026-09-17 | U | Fase 05: DSL con traducción al castellano; el resto, como se propuso | [→](03-plan-y-proceso.md#dp-08) |
| DP-09 | 2026-09-17 | U | Fase 06: modelo aprobado; F1-11 se parte en imagen (a) y k3s (b) | [→](03-plan-y-proceso.md#dp-09) |
| DP-10 | 2026-09-18 | U | Fase 07: el tag no espera al GXDCH | [→](03-plan-y-proceso.md#dp-10) |
| DP-11 | 2026-09-20 | U | Fase 08: la prueba con usuario de negocio (F08-98) no bloquea el tag | [→](03-plan-y-proceso.md#dp-11) |
| DP-12 | 2026-09-21 | U | El repositorio se sube a un GitHub público; el push lo hacemos a mano | [→](03-plan-y-proceso.md#dp-12) |
| DP-13 | 2026-09-22 | U | Verificación proporcional: solo lo tocado, salvo cierres y cambios transversales | [→](03-plan-y-proceso.md#dp-13) |
| DP-14 | 2026-09-23 | U | Fase 09: registro de seguridad en tabla encadenada, TOTP para dos roles e integrar la rama de auditoría | [→](03-plan-y-proceso.md#dp-14) |
| DP-15 | varias | U | Las tareas que esperan hardware, accesos o contratos son MANUAL y no bloquean el cierre de su fase | [→](03-plan-y-proceso.md#dp-15) |

Las decisiones técnicas tomadas dentro de las tareas (unas 90) están agrupadas por fase en [03 · Plan y proceso](03-plan-y-proceso.md#decisiones-técnicas-dentro-de-las-tareas). Las 26 notas de desviación, en [02 · Desviaciones](02-desviaciones.md).
