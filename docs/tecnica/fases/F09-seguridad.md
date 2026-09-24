---
id: FASE-09
kind: phase
title: Fase 09 · Seguridad de plataforma
phase: "09"
version: 0.1.0-alpha
commit: 0d9c9ed
date: 2026-09-24
status: current
confidentiality: client
---

# Fase 09 · Seguridad de plataforma

> **Endurecer la caja, probado sin la caja.** Todo lo que el appliance necesita está construido y probado en el entorno de desarrollo (ADR-0014). Lo que exige el equipo físico —imagen endurecida, Secure Boot, disco sellado al TPM y k3s— está escrito y probado sin hardware, y espera a F09-90, F09-91 y F09-92. El dossier dice en cada medida cuál de las dos cosas es.

## 1. Resumen

La Fase 09 convierte ARGOS en un sistema que se puede presentar a un proceso ENS o ISO 27001 con evidencia.

- **Identidad y sesiones:** quien decide entra con segundo factor. Cada servicio habla con los demás por TLS mutuo y con la base de datos con su propio usuario, que Vault crea y retira. Una sesión cerrada deja de valer al momento.
- **Registro de seguridad:** lleva su propia cadena y sus alertas, aparte del diario funcional.
- **Actualizaciones:** solo se aplican si están firmadas, y vuelven solas atrás si el servicio no arranca sano.
- **Soporte:** sin acceso remoto. El operador ve el paquete de diagnóstico antes de enviarlo.
- **Copias:** están cifradas, y solo cuentan cuando su restauración se ha probado y fechado.
- **Esclusa:** en el appliance aislado, todo lo que entra o sale pasa por ella, con verificación a la entrada y una lista cerrada a la salida.
- **Revisión de F1–F8:** tratamos sus hallazgos como los de un cliente: registrados, corregidos y evidenciados.
- **Batería de accesos indebidos:** ataca la API desplegada con tokens reales, y su informe va al dossier.

## 2. Alcance

- **Incluido:**
  - ARG-081 a ARG-090;
  - modelo de amenazas;
  - revisión de seguridad de las fases 01 a 08 (SEC-001…057) y sus correcciones (F09-20…F09-31);
  - un rol de base de datos por servicio y credenciales dinámicas;
  - mTLS interno;
  - segundo factor;
  - registro de seguridad;
  - batería de accesos indebidos (SEC-058…060, corregidos en F09-15 y F09-32);
  - dossier de seguridad v1 para ENS categoría media e ISO/IEC 27001:2022.
- **Fuera, porque espera el hardware:**
  - imagen endurecida real con puntuación CIS ≥ 90 % (F09-90);
  - Secure Boot, arranque medido, LUKS sellado al TPM y ciclo de vida de claves en el TPM (F09-91);
  - cert-manager, Kyverno, AppArmor, firma de imágenes y autenticación de Vault en k3s (F09-92).
- **Fuera, porque es una decisión:** entregar el dossier al proceso de certificación (F09-97).

## 3. Entregables

| Módulo | Documento | Versión |
|---|---|---|
| argos-tls (nuevo) | `modulos/argos-tls.md` | 0.1.0-alpha |
| argos-updater (nuevo) | `modulos/argos-updater.md` | 0.1.0-alpha |
| argos-support (nuevo) | `modulos/argos-support.md` | 0.1.0-alpha |
| argos-airgap (nuevo) | `modulos/argos-airgap.md` | 0.1.0-alpha |
| argos-api (ampliado) | `modulos/argos-api.md` | 0.34.0-alpha |
| argos-auth (ampliado) | `modulos/argos-auth.md` | 0.3.0-alpha |
| argos-common (ampliado) | `modulos/argos-common.md` | 0.12.0-alpha |
| argos-console (ampliado) | `modulos/argos-console.md` | 0.13.0-alpha |
| argos-evidence (ampliado) | `modulos/argos-evidence.md` | 0.20.0-alpha |
| argos-verifier (ampliado) | `modulos/argos-verifier.md` | 0.4.0-alpha |
| argos-connector-sdk (ampliado) | `modulos/argos-connector-sdk.md` | 0.5.0-alpha |
| argos-ai-gateway (ampliado) | `modulos/argos-ai-gateway.md` | 0.8.0-alpha |

Documentos de seguridad en `docs/seguridad/`:

- modelo de amenazas;
- revisión de F1–F8;
- batería de accesos;
- backup y restauración;
- endurecimiento de la imagen;
- dossier ENS/ISO.

## 4. Prueba de la fase

**Criterio del Plan Director §8.2:**

- la batería de intentos de acceso indebido (matriz rol × recurso) en verde;
- la restauración completa desde copia en entorno limpio, con verificación de la cadena del diario;
- una actualización sin firma válida, rechazada;
- el dossier de seguridad v1 entregado al proceso de certificación.

**Cómo se ejecutó:**

- **Entorno:** `make dev` con todos los contenedores, Keycloak con los cuatro roles, Vault, PostgreSQL con TLS y el almacén WORM.
- **Datos:** exclusivamente sintéticos.
- **Pruebas:** `tests/e2e/test_phase9_acceptance.py`, más `make check`, `make console-e2e`, `make restore-test` y `make sbom`.

**Resultado, 2026-09-24:** todos los criterios en verde en el entorno de desarrollo.

1. **La batería de accesos pasa entera contra la API desplegada:**
   - matriz de los cuatro roles, sin efecto en el diario;
   - tokens falsificados, caducados, de otra audiencia y de una sesión cerrada, todos rechazados;
   - separación de deberes;
   - superficie y servicios internos.

   La cadena del registro de seguridad verifica.
2. **Restauración desde copia en un PostgreSQL desechable sin red:**
   - cadenas del diario y del registro de seguridad íntegras;
   - recuentos coherentes con producción;
   - la fecha de la prueba publicada en su métrica.
3. **Actualizaciones:**
   - una sin firma, con firma de otra clave o con una imagen de otro digest se rechaza sin tocar ningún servicio;
   - una firmada cuyo servicio nunca queda sano vuelve sola a la versión anterior;
   - las dos también entrando por la esclusa.
4. **Postura:**
   - ningún contenedor de ARGOS corre como root, con capacidades ni pudiendo ganar privilegios;
   - toda conexión a PostgreSQL va cifrada;
   - ningún usuario de servicio supera su caducidad.
5. **El dossier v1 se genera** con todas sus evidencias presentes y su manifiesto verificado. La entrega al proceso de certificación es F09-97, una decisión del usuario, declarada y sin bloquear el tag.

## 5. Decisiones y desviaciones

- **ADR-0014 · Seguridad de plataforma sin appliance.** Todo lo que se puede probar en el compose se construye y se prueba ya; lo que exige hardware se escribe, se prueba sin él y espera a su tarea manual.
- **Nota ARG-081-090 (aprobada):**
  - firma Ed25519 del manifiesto en lugar de cosign;
  - órdenes como listas de argumentos, nunca `shell=True`;
  - diario y registro de seguridad en toda operación.
- **Notas propuestas, pendientes de aprobación:**
  - **ARG-085:** credenciales dinámicas en el compose;
  - **ARG-086:** actualizador en el anfitrión de desarrollo;
  - **ARG-089:** volcado diario sin WAL hasta la Fase 10, scripts en Python y temporizadores de systemd;
  - **ARG-081-082:** `usb-storage` disponible para la esclusa, clave de recuperación nunca en disco y resellado en dos pasos.
- **Registro de decisiones:** cada decisión técnica de la fase está en `docs/decisiones/03-plan-y-proceso.md`, con su motivo y lo comprobado.

## 6. Interfaces que exporta

`docs/fases/interfaces-F09.md`. Lo que consume la Fase 10:

- el actualizador y la esclusa, para desplegar y mantener;
- el backup y sus alertas;
- el registro de seguridad y sus métricas;
- el paquete de diagnóstico;
- el dossier, que la operación mantiene al día.

## 7. Pendientes al cierre

- **Hardware:**
  - F09-90: imagen endurecida real y puntuación CIS;
  - F09-91: Secure Boot, arranque medido y TPM;
  - F09-92: seguridad de k3s;
  - F07-15: firma con el TPM.

  Todo está escrito y probado sin el equipo.
- **Decisión del usuario:** F09-97, entregar el dossier al proceso de certificación. La aplicabilidad de cada medida a categoría media la decide el organismo en su Declaración de Aplicabilidad.
- **Notas de desviación propuestas:** ARG-085, ARG-086, ARG-089 y ARG-081-082.
- **Operación (Fase 10):**
  - archivado de WAL y destino real de las copias (S3 o SFTP del cliente), con la medición del RTO;
  - temporizadores del backup y recolector de diagnóstico como servicios del nodo;
  - cierre de sesión desde Keycloak (back-channel logout);
  - clave real del soporte y remontaje del soporte de la esclusa.
- **Pruebas:** un test de Keycloak (`test_keycloak_mfa.py`) falla a veces en la suite completa y pasa siempre aislado. Está apuntado para investigarlo.

## 8. Identificación del cierre

Tag `fase-09` sobre el commit indicado arriba, 2026-09-24. Sin subir: el `push` lo hace el usuario.
