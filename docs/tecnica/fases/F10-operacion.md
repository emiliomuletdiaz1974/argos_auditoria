---
id: FASE-10
kind: phase
title: Fase 10 · Operación y despliegue
phase: "10"
version: 0.1.0-alpha
commit: pendiente
date: 2026-09-25
status: current
confidentiality: client
---

# Fase 10 · Operación y despliegue

> **Operar la caja, probado sin la caja.** ARGOS se vigila, avisa, se dimensiona, se instala y se verifica a sí mismo en el entorno de desarrollo (ADR-0015). La instalación en el hardware, la comprobación de sala medida y la alta disponibilidad en nodos reales esperan a F10-90, F10-91 y F10-92; publicar la v1.0 es una decisión (F10-97), y después viene el piloto.

## 1. Resumen

La Fase 10 hace de ARGOS algo que un organismo puede operar sin nosotros.

- **ARGOS verifica ARGOS:** retos `self-*` sobre el propio appliance, con un reto trampa que debe fallar siempre, y una puerta de release que bloquea si el diario no verifica o hay hallazgos graves.
- **Salud del dominio:** un servicio mide lo que un monitor genérico no ve (diario, registro de seguridad, WORM, certificados, exploraciones, capacidad) y lo publica para Prometheus y para la autoverificación.
- **Alertas y paneles:** las reglas se generan desde los objetivos de la especificación, cada una con su runbook; los paneles se aprovisionan desde el repositorio, de solo lectura.
- **Logs:** cada servicio empuja sus líneas a Loki; un Loki caído no detiene nada, y lo que se pierde se cuenta.
- **Libro de operación:** doce runbooks con cinco secciones cada uno, simulacro sorteado y cronometrado que queda en el diario, y una pantalla de operación en la consola.
- **Tallas:** límites de S, M y L, rechazo honesto con las cifras y las opciones, y serie diaria de 13 meses.
- **Alta disponibilidad:** conmutación asistida de la talla M probada con una pareja propia; configuración de la L con quórum y replicación síncrona.
- **Instalación:** el instalador de la semana 1, con configuración validada, órdenes sin shell, reanudación e informe firmado, y la comprobación de sala con analizadores probados.

## 2. Alcance

- **Incluido:** ARG-091 a ARG-100.
- **Fuera, porque espera el hardware:**
  - instalación completa desde cero en el equipo de laboratorio (F10-90);
  - comprobación de sala medida en el equipo, con capturas reales de `ipmitool` y `nvidia-smi` (F10-91);
  - alta disponibilidad en nodos reales: M en dos nodos y L con quórum (F10-92).
- **Fuera, porque es una decisión:** publicar la release v1.0 con su expediente de autoverificación (F10-97).
- **Después:** el piloto de seis semanas en el demostrador de salud (P-01…P-06), que empieza cuando se publique la v1.0.

## 3. Entregables

| Módulo | Documento | Versión |
|---|---|---|
| argos-health (nuevo) | `modulos/argos-health.md` | 0.5.0-alpha |
| argos-installer (nuevo) | `modulos/argos-installer.md` | 0.2.0-alpha |
| argos-api (ampliado) | `modulos/argos-api.md` | 0.38.0-alpha |
| argos-common (ampliado) | `modulos/argos-common.md` | 0.14.1-alpha |
| argos-console (ampliado) | `modulos/argos-console.md` | 0.16.0-alpha |
| argos-airgap (ampliado) | `modulos/argos-airgap.md` | 0.2.0-alpha |
| argos-challenge-engine (ampliado) | `modulos/argos-challenge-engine.md` | 0.12.0-alpha |
| argos-connector-sdk (ampliado) | `modulos/argos-connector-sdk.md` | 0.6.0-alpha |
| argos-inventory (ampliado) | `modulos/argos-inventory.md` | 0.6.0-alpha |
| argos-ontology (ampliado) | `modulos/argos-ontology.md` | 0.6.0-alpha |

Además:

- `docs/operacion/`: el libro de operación (RB-01…RB-12) y la alta disponibilidad;
- `platform/observability/`: objetivos, reglas y paneles;
- `platform/operation/`: tallas, límites de sala y ejemplo del instalador;
- `platform/ha/`: conmutación de la M y configuración de la L;
- `docs/seguridad/`: modelo de amenazas 1.24 y dossier ENS 1.1 con las superficies y la evidencia de la fase.

## 4. Prueba de la fase

**Criterio del Plan Director §8.2:**

- instalación desde cero siguiendo solo el instalador;
- simulacro cronometrado de dos runbooks;
- release v1.0 con su expediente de autoverificación.

**Cómo se ejecutó:**

- **Entorno:** `make dev` con todos los contenedores, más Prometheus, Alertmanager, Grafana, Loki y el servicio de salud; la pareja `ha` para la conmutación.
- **Datos:** exclusivamente sintéticos.
- **Pruebas:** `tests/e2e/test_phase10_acceptance.py`, más `make check`, `make console-e2e`, `make selfcheck`, `make restore-test` y `make sbom`.

**Resultado, 2026-09-25:** todos los criterios en verde en el entorno de desarrollo.

1. **Autoverificación:** la campaña `self-*` se sella con solo el reto trampa como hallazgo y la puerta pasa; con el diario roto en una base desechable, la puerta bloquea.
2. **Alertas:** las críticas (diario, WORM, disco y restauración) existen y cada runbook citado existe. Cada una se dispara sobre su causa: series de prueba con promtool y un diario roto que el servicio de salud lee como no íntegro. Una alerta de Alertmanager llega a la API con su runbook para la consola.
3. **Simulacro:** dos runbooks sorteados, recorridos y cronometrados, con su asiento `ops.drill` en el diario.
4. **Instalador:** una ejecución completa con dobles del hardware produce el informe firmado con la clave de release de Vault, que verifica. La comprobación de sala da «apto» para una S con las salidas de referencia; la misma sala detiene una M por el enlace de 10 Gbps y dice por qué.
5. **Tallas:** una S rechaza su sistema número 41 con un `409` que da las cifras y las opciones.
6. **Talla M:** con el principal caído, la réplica se promueve con el diario íntegro y el antiguo principal se reincorpora; con el principal vivo, la conmutación se niega.

**Cómo se provocan las alertas:** no rompemos el diario ni llenamos el disco del entorno compartido. Las causas se provocan con series de prueba de promtool y, en el caso del diario, con una base desechable. La entrega de Alertmanager a la API sí es de extremo a extremo.

## 5. Decisiones y desviaciones

- **ADR-0015 · Operación sin appliance.** Lo que se puede probar en el compose se construye y se prueba ya; lo que exige hardware se escribe, se prueba sin él y espera a su tarea manual. Los servicios empujan sus logs a Loki, sin recolector con acceso al socket de Docker (punto 4, opción B).
- **Nota ARG-091-100 (aprobada en F10-00).**
- **Durante la prueba de la fase** corregimos el recuento de campañas en paralelo: ocupa plaza la campaña que corre o espera en una compuerta viva, no toda la que está `pinned`.
- **Registro de decisiones:** cada decisión técnica de la fase está en `docs/decisiones/03-plan-y-proceso.md`, con su motivo y lo comprobado.

## 6. Interfaces que exporta

`docs/fases/interfaces-F10.md`. Lo que consume el piloto:

- el instalador y su lista previa de sala;
- el libro de operación y la pantalla de operación;
- las alertas y los paneles;
- la autoverificación como puerta de cada release.

## 7. Pendientes al cierre

- **Hardware:**
  - F10-90: instalación completa desde cero en el hardware de laboratorio;
  - F10-91: comprobación de sala medida, con capturas reales de `ipmitool` y `nvidia-smi`;
  - F10-92: alta disponibilidad en nodos reales.

  También siguen F1-11a, F1-11b, F06-98, F07-15 y F09-90…92.
- **Decisión del usuario:** F10-97, publicar la release v1.0 con su expediente de autoverificación.
- **Piloto:** P-01…P-06, después de F10-97.
- **Operación:**
  - Loki no conserva las líneas al reiniciarse en desarrollo;
  - el canario del WORM necesita su limpieza y su propia cuenta de S3;
  - tres objetivos siguen sin medida: primer token, latencia de la consola y ritmo de sellado;
  - el appliance aún no explora sus propias tablas;
  - la autoverificación corre en el proceso, no en el worker desplegado;
  - una campaña cuya compuerta caduca se queda `pinned`: ya no ocupa plaza, pero debería pasar a `failed`.
- **Pruebas:** el test de Keycloak (`test_keycloak_mfa.py`) sigue fallando a veces en la suite completa y pasando aislado.

## 8. Identificación del cierre

Tag `fase-10` sobre el commit indicado arriba, 2026-09-25. Sin subir: el `push` lo hace el usuario.
