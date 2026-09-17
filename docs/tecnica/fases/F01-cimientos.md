---
id: FASE-01
kind: phase
title: Fase 01 · Cimientos de la plataforma
phase: "01"
version: 0.1.0-alpha
commit: 6787b19
date: 2026-09-14
status: current
confidentiality: client
---

# Fase 01 · Cimientos de la plataforma

## 1. Resumen

La Fase 01 construye la base sobre la que funciona todo ARGOS:
- configuración que impide arrancar un servicio mal configurado;
- registro estructurado;
- un **diario de auditoría encadenado** que no se puede alterar sin que se detecte;
- bus de eventos;
- orquestación de flujos de trabajo;
- validación de identidades;
- gestión de secretos;
- una **release firmada** que el appliance puede verificar sin conexión.

## 2. Alcance

- **Componentes incluidos:** ARG-001, ARG-004 a ARG-010.
- **Fuera de la fase:** la imagen inmutable del appliance y el plano k3s (ARG-002 y ARG-003) se aplazaron hasta disponer del hardware del Servidor Cognitivo (nota de desviación ARG-002-003). Mientras tanto, el entorno equivalente es Docker Compose con los mismos servicios.

## 3. Entregables

| Módulo | Documento | Versión |
|---|---|---|
| Librería común | [`modulos/argos-common.md`](../modulos/argos-common.md) | 0.1.0-alpha |
| Bus de eventos | [`modulos/argos-events.md`](../modulos/argos-events.md) | 0.1.0-alpha |
| Validación de identidades | [`modulos/argos-auth.md`](../modulos/argos-auth.md) | 0.1.0-alpha |
| Motor de retos (base) | [`modulos/argos-challenge-engine.md`](../modulos/argos-challenge-engine.md) | 0.1.0-alpha |

Además:
- el esquema núcleo de PostgreSQL con el diario (migración `0001_core.sql`);
- el entorno de desarrollo con PostgreSQL, NATS, Temporal, Keycloak, Vault, Prometheus, Loki y Grafana;
- el CI en GitHub Actions con las etapas de verificación, construcción, empaquetado y firma declaradas.

## 4. Prueba de la fase

**Criterio del Plan Director:**
- servicios sanos;
- un servicio escribe 100 asientos en el diario y la verificación los da por íntegros;
- una corrupción deliberada se detecta con su posición;
- la release sale firmada y verificable.

**Ejecución:** entorno de desarrollo limpio, con datos sintéticos, y test `tests/e2e/test_phase1_acceptance.py`.

**Resultado (2026-09-14):**
- prueba de aceptación: 2 de 2;
- `make check`: 120 tests, con lint, tipos y detección de secretos limpios;
- cobertura del 97,62 %;
- parada limpia del servicio;
- manifiesto construido, firmado y verificado (`valid signature`), con la imagen fijada por digest.

## 5. Decisiones y desviaciones

- **ADR-0001:** alcance de la Fase 1 y estructura en monorepo.
- **ADR-0002:** especificación única del diario encadenado v1. Canonicalización, hash con prefijos de longitud y versión, y secuencia bajo bloqueo; corrige ambigüedades y bifurcaciones del diseño original.
- **ADR-0003:** herramientas y CI en GitHub Actions en lugar de GitLab.
- **ADR-0005:** código en inglés y documentación en castellano.
- **Nota ARG-002-003:** appliance y k3s aplazados hasta tener hardware.
- **Nota ARG-005:** esquema del diario según ADR-0002.
- **Nota ARG-010:** firma del manifiesto con Vault Transit (Ed25519); la firma cosign de imágenes espera a un registro interno.

## 6. Interfaces que exporta

Tabla completa en `docs/fases/interfaces-F01.md`. Las Fases 02 a 10 consumen:
- configuración, registro, salud y errores comunes;
- el diario de auditoría;
- el bus de eventos;
- el patrón de workflows de Temporal;
- la validación de identidades;
- los almacenes de secretos;
- el manifiesto firmado.

## 7. Pendientes al cierre

- **Imagen del appliance y k3s (ARG-002/003):** a la espera de hardware.
- **Duración del CI** en el primer envío al repositorio remoto: el objetivo es menos de 10 minutos.
- **Sellado de secretos en TPM:** Fase 09.
- **Firma cosign de imágenes:** con un registro interno.
- **Registros de acceso del servidor HTTP en JSON:** Fase 10.

## 8. Identificación del cierre

Tag `fase-01`, commit `6787b19`, 2026-09-14.
