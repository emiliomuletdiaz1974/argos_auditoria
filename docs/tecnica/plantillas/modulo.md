---
id: MOD-<nombre-del-paquete>
kind: module
title: <Nombre legible del módulo>
module: <nombre del paquete en pyproject.toml, p. ej. argos-inventory>
phases: ["NN"]
version: <versión del paquete>
commit: <hash corto del commit que deja el documento al día>
date: <AAAA-MM-DD>
status: current
confidentiality: client
---

# <Nombre legible del módulo>

## 1. Propósito

Qué problema resuelve el módulo y para quién, en dos o tres frases. Componentes del catálogo ARG que implementa.

## 2. Alcance y límites

- Qué hace.
- Qué no hace, de forma explícita (por ejemplo: «nunca escribe en los sistemas del cliente»).

## 3. Arquitectura

- Piezas principales (paquetes, clases o procesos) y cómo se relacionan.
- Dependencias con otros módulos de ARGOS y con servicios externos (PostgreSQL, NATS, Vault…).
- Diagrama opcional en Mermaid.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| API / función pública | | |
| Evento publicado o consumido | | |
| Tabla o migración | | |
| Herramienta de línea de órdenes | | |

## 5. Configuración

Variables de entorno, valores por defecto y secretos que necesita, indicando dónde se guardan (nunca los valores).

## 6. Seguridad y tratamiento de datos

- Datos que lee, escribe o conserva y su clasificación.
- Controles aplicados: solo lectura, minimización, cifrado, diario de auditoría, firma.
- Decisiones y desviaciones aplicables (ADR, notas ARG-NNN).

## 7. Operación

Cómo se arranca, se comprueba su salud, qué registra y qué hacer ante los fallos habituales.

## 8. Verificación

Pruebas que lo cubren (unitarias, de integración y de fase) y resultado de la última ejecución.

## 9. Limitaciones conocidas y pendientes

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
