---
id: FASE-07
kind: phase
title: Fase 07 · Evidencia y credencial
phase: "07"
version: 0.1.0-alpha
commit: b9adf20
date: 2026-09-18
status: current
confidentiality: client
---

# Fase 07 · Evidencia y credencial

> **Firma, sello y espacio de datos de desarrollo.** La cadena está completa y probada de extremo a extremo, pero en esta fase la raíz se firma con una clave de Vault y no con el TPM del appliance. El sello de tiempo lo pone una autoridad de pruebas, no una cualificada eIDAS, y el conector EDC es una simulación. Todo lo firmado lo declara (`non_production`) y el comprobador lo muestra. Las piezas reales llegan con F07-15 y F07-16.

## 1. Resumen

La Fase 07 convierte los resultados de una campaña en **prueba**: algo que un auditor, un inspector o la otra parte de un contrato puede comprobar sin fiarse de ARGOS. Cada veredicto se guarda como un artefacto inmutable en un almacén que ni su administrador puede borrar. Todos los artefactos de la campaña quedan encadenados en un árbol de Merkle, cuya raíz se firma y se sella en el tiempo junto con el estado del diario de auditoría. De ahí salen un expediente legible, en JSON y PDF, y una credencial verificable W3C que lo respalda por su hash. Un comprobador público revisa todo el conjunto pieza a pieza y, si algo se tocó, dice exactamente qué.

## 2. Alcance

- **Incluido:** ARG-061 a ARG-070: almacén WORM, artefactos, árbol de Merkle, firma de la raíz, sellado temporal RFC 3161 con cola y modo aislado, anclaje del diario, expediente, credencial verificable, comprobador público y publicación en espacios de datos; el cierre de campaña encadenado y los contenedores del servicio; el kit de la demostración del MVP.
- **Fuera:** la firma con el TPM del appliance (F07-15, espera hardware), la TSA cualificada, el conector EDC real y Pontus-X (F07-16, esperan contratos), la verificación con las herramientas del GXDCH (F07-14, espera el alta; no bloquea este cierre por decisión de F07-00) y la consola (Fase 08).

## 3. Entregables

| Módulo | Documento | Versión |
|---|---|---|
| argos-evidence | `modulos/argos-evidence.md` | 0.11.0-alpha |
| argos-verifier | `modulos/argos-verifier.md` | 0.1.0-alpha |
| argos-common (ampliado) | `modulos/argos-common.md` | 0.1.0-alpha |
| argos-challenge-engine (ampliado) | `modulos/argos-challenge-engine.md` | 0.1.0-alpha |

## 4. Prueba de la fase

Criterio del Plan Director §8.2: la campaña de la Fase 05 termina en un expediente JSON y PDF; la raíz de Merkle verifica, y una evidencia corrupta rompe la verificación señalando la pieza; la credencial emitida se verifica con el comprobador público (y con las herramientas del GXDCH, ver §7); el hito MVP auditable queda demostrado en una demostración grabada de 30 minutos.

Se ejecutó con `make dev` (fuentes simuladas, Temporal, Vault, almacén WORM, TSA de pruebas y los contenedores de evidencia y del comprobador) sobre datos exclusivamente sintéticos, en `tests/e2e/test_phase7_acceptance.py`. Esa prueba recorre el mismo guion que la demostración (`tools/demo/run_mvp_demo.py`), sobre la instantánea y la verdad terreno de la Fase 05 y con una base de datos propia por ejecución.

Resultado, 2026-09-18: todos los criterios técnicos en verde.

1. **Expediente y credencial:** la campaña de la Fase 05 (sellada, con el reto estrella del borrado efectivo en incumplimiento en la réplica de facturación) termina en un expediente JSON y PDF guardado en el WORM y en una credencial.
2. **La raíz verifica y lo corrupto se señala:** el paquete de verificación pasa todas las comprobaciones. Un byte cambiado en el expediente, en el sobre firmado, en el token de sello o en un artefacto falla exactamente en `dossier_hash`, `root_signature`, `timestamp` o `artifact_inclusion[i]`, con la posición del artefacto.
3. **Inmutabilidad:** el almacén rechaza borrar y sobrescribir el expediente, que sigue intacto.
4. **Comprobador público:** el contenedor del comprobador verifica el paquete. Tras revocar la credencial, la misma credencial, sin tocarla, falla solo en `credential` con el motivo `revoked`.

La **demostración grabada** la hace una persona con el guion `docs/demo/guion-mvp.md` y queda como pendiente.

## 5. Decisiones y desviaciones

- **ADR-0010 · Almacén WORM.** La garantía la da una prueba de conformidad, no la documentación; sin AGPL. VersityGW pasó la prueba: borrar, acortar la retención o relajar el modo se rechazan, también a la cuenta raíz.
- **ADR-0011 · Credencial verificable.** VC 2.0 con `eddsa-jcs-2022`, emisor `did:web`, revocación por Bitstring Status List y ningún dato personal.
- **Nota ARG-064-065.** En desarrollo se firma con la clave no exportable de Vault Transit y se sella con una TSA local de pruebas, ambas marcadas como no productivas.
- **Nota ARG-066.** No hay un segundo verificador del diario; la Fase 07 aporta el anclaje de su cabeza en la firma.
- **Nota ARG-062.** El artefacto lleva la fecha del veredicto, no la de escritura, para que el mismo veredicto dé siempre los mismos bytes.
- **Nota ARG-067.** El PDF se genera con ReportLab (BSD), no con `markdown-pdf`, que depende de PyMuPDF (AGPL), y el expediente no lleva momento de ensamblado.
- **Decisión del usuario (F07-00):** el cierre de la fase no espera al GXDCH.

## 6. Interfaces que exporta

`docs/fases/interfaces-F07.md`. Lo que consumen las fases siguientes: la Fase 08 muestra y descarga expedientes, credenciales y paquetes de verificación; la Fase 09 completa el ciclo de claves con TPM y cierra el acceso de superusuario al almacén; la Fase 10 opera el almacén (retenciones, expiración del bucket de trabajo) y distribuye el comprobador.

## 7. Pendientes al cierre

- **Verificación de la credencial con las herramientas del GXDCH** (F07-14): necesita el alta del participante.
- **Firma con TPM** (F07-15) y **TSA cualificada, conector EDC real y Pontus-X** (F07-16).
- **PDF del expediente sin firma propia.** Hoy lo respalda la cadena: el PDF se genera solo desde el JSON, lleva su hash en cada página, y ese hash lo cita la credencial firmada. Firmar también el PDF (PAdES) queda para cuando la firma esté en el TPM.
- **Almacén WORM frente al superusuario del appliance** (Fase 09) y **expiración del bucket `working`** (Fase 10).
- **Distribución del comprobador sin las dependencias de la plataforma** (Fase 10).
- **Grabación de la demostración y dos diapositivas** (persona).
- **Sesiones en paralelo sobre el mismo entorno de desarrollo:** sus tests se interfieren; decisión del usuario.
- La lista completa está en `ARGOS-pendientes.md`.

## 8. Identificación del cierre

Tag `fase-07`, 2026-09-18. El tag se pone sobre el commit de documentación que sigue a la prueba de la fase.
