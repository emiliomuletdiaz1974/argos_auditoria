# Modelo de amenazas del appliance ARGOS

**Versión:** 1.11 · **Fecha:** 2026-09-23 · **Base:** `main` tras la Fase 08 · **Confidencialidad:** `client`
**Componentes:** ARG-081…090 y lo construido en las Fases 01–08 · **Decisión de referencia:** ADR-0014

ARGOS es una caja que ve los metadatos más sensibles de su cliente, se instala en su sala y la administra su personal. Este documento dice **qué protegemos, frente a quién, por dónde podrían entrar y qué lo impide**. Es la base del dossier para ENS categoría media e ISO/IEC 27001, y cada control de la Fase 09 responde a una amenaza escrita aquí.

## 1. Método

- **STRIDE por superficie:** suplantación (S), manipulación (T), repudio (R), revelación de información (I), denegación de servicio (D) y elevación de privilegios (E).
- **Fuentes:**
  - ADR-0001…0014 y las notas de desviación de `docs/desviaciones/`;
  - las interfaces de `docs/fases/interfaces-F01…F08.md`;
  - el Pliego (P-02, P-03, P-04, P-05, P-06, P-22, P-23 y P-25);
  - el código de `main`.
- **Estado de cada mitigación:**
  - `implementada`: existe en `main` y se puede comprobar en la ruta de la columna *Evidencia* (un test lo exige);
  - `en desarrollo`: tiene tarea en la Fase 09 y todavía no está en `main`;
  - `pendiente de hardware`: necesita el appliance (TPM, Secure Boot o k3s).
- **Límite honesto:** lo `implementado` se ha probado en el entorno de desarrollo (Docker Compose), no en el appliance. Lo que cambia al pasar al appliance está en §6.

## 2. Activos

| Activo | Dónde vive | Qué hay que proteger |
|---|---|---|
| Metadatos del inventario y grafo (esquemas, columnas, clasificaciones, flujos) | PostgreSQL + Apache AGE | Confidencialidad e integridad |
| Credenciales de los conectores hacia sistemas del cliente | Vault (`argos/data/connectors/*`) | Confidencialidad (P-04) |
| Claves de firma: release, contenido normativo y raíz de campaña | Vault transit (en el appliance, TPM) | No extracción e integridad |
| Diario de auditoría | `argos.audit_journal` | Integridad y no repudio |
| Veredictos y hallazgos | `argos.verdicts`, `argos.findings` | Integridad: solo el evaluador y la reejecución los cambian |
| Evidencia sellada | Almacén WORM (VersityGW) | Integridad y conservación |
| Credenciales verificables emitidas | WORM y `argos.credentials` | Autenticidad y estado de revocación |
| Modelo local, prompts y conjuntos dorados | Servidor de inferencia y `library/prompts/` | Integridad (lo que el LLM puede hacer) |
| Copias de seguridad | Destino del cliente | Confidencialidad e integridad |
| Paquete de diagnóstico | Soporte extraíble del cliente | Confidencialidad (nada de negocio) |

## 3. Adversarios

| ID | Adversario | Capacidad supuesta | Qué buscaría |
|---|---|---|---|
| A1 | Atacante en la red del cliente | Alcanza los puertos del appliance; no tiene credenciales | Suplantar servicios, escuchar el tráfico interno, entrar por la API |
| A2 | Contenedor comprometido | Ejecución de código en un conector o servicio (p. ej. por una fuente que devuelve datos maliciosos) | Escribir en sistemas del cliente, moverse a otros servicios, leer secretos |
| A3 | Administrador del cliente, malicioso o descuidado | Root en el sistema operativo y acceso a la consola física | Borrar o alterar evidencia, rebajar un hallazgo, desactivar controles |
| A4 | Acceso físico | Se lleva el disco o arranca el equipo desde un USB | Leer los datos en reposo y extraer claves |
| A5 | Cadena de suministro | Manipula una dependencia, una imagen o un paquete de actualización | Ejecutar código propio con la confianza del fabricante |
| A6 | Soporte del fabricante | Quiere entrar para diagnosticar, o alguien que se hace pasar por él | Acceso remoto que P-06 prohíbe |
| A7 | Datos inventariados hostiles | Textos en la fuente del cliente pensados para manipular al LLM | Que el LLM decida un veredicto, escriba o filtre datos |
| A8 | Usuario legítimo que se excede | Cuenta válida de la consola con un rol | Actuar fuera de su rol: aprobar lo propio, cerrar hallazgos a mano |

## 4. Superficies

| Superficie | Expuesta a | Notas |
|---|---|---|
| API v1 y consola (`argos-api`, puerto 8000) | A1, A8 | Única API autenticada (ADR-0012) |
| `evidence-api` y comprobador público | A1 | Sin credenciales por diseño: solo material público |
| Conectores hacia sistemas del cliente | A2, A7 | Solo lectura por construcción |
| Bus NATS, Temporal, PostgreSQL y Vault | A1, A2 | Red interna del appliance |
| Gateway de IA y modelo local | A2, A7 | Aislado del veredicto (Fase 06) |
| Actualizador y esclusa de soportes | A3, A5 | Lo que entra desde fuera |
| Disco, arranque y consola física | A3, A4 | Hardware del appliance |
| Canal de soporte | A6 | No hay canal remoto: solo paquetes de diagnóstico |

## 5. Mitigaciones

| ID | Amenaza (STRIDE) | Superficie | Adversarios | Mitigación | Componente | Tarea | Estado | Evidencia |
|---|---|---|---|---|---|---|---|---|
| M-01 | T: escribir en un sistema del cliente | Conectores | A2, A3 | Solo lectura por construcción: validación sintáctica con sqlglot (una sentencia, sin nodos de escritura, sin comentarios que el motor ejecute, sin pistas de bloqueo, funciones denegadas por segmento y funciones no modeladas solo de catálogo), sesión de solo lectura con tiempo máximo y `execute()` final | ARG-011, ARG-014 | F02-01, F09-21 | implementada | `connectors/sdk/argos_connector/readonly.py`, `connectors/sdk/tests/test_sdk_readonly.py` |
| M-02 | R: negar qué se consultó en un sistema del cliente | Conectores | A2, A3 | Diario previo de consultas: la sentencia literal queda asentada antes de tocar el sistema, también la exploración de esquema, las páginas que elige el servidor y la asociación DICOM, y los rechazos | ARG-012 | F02-02, F09-22 | implementada | `connectors/sdk/argos_connector/journal.py`, `tests/integration/test_query_journal_pg.py` |
| M-03 | D: saturar un sistema del cliente | Conectores | A2 | Presupuesto de carga compartido por sistema entre todos los procesos (fila en PostgreSQL), ventanas horarias, tope de filas por sonda y cortacircuitos que pausa las campañas | ARG-013 | F02-03, F09-22 | implementada | `connectors/sdk/argos_connector/budget_pg.py`, `tests/integration/test_shared_budget.py` |
| M-04 | I: traer datos del cliente a ARGOS | Conectores | A2, A3 | Minimización: digests HMAC por sistema y tasas de validación, nunca valores en claro; `check_config` solo lee catálogo y configuración, devuelve en claro solo ajustes y con tope de filas; la muestra DICOM no pide al paciente | ARG-011, ARG-024 | F02-01, F09-31 | implementada | `connectors/sdk/argos_connector/minimize.py`, `connectors/sdk/argos_connector/config_sources.py`, `connectors/sql/tests/test_sql_hardening.py` |
| M-05 | T/R: alterar o borrar el diario | PostgreSQL | A2, A3 | Cadena hash v1 con `seq` sin huecos, escritura solo por `journal_append` y triggers contra UPDATE, DELETE y TRUNCATE; verificador independiente (huecos de la revisión F09-02, ver `docs/seguridad/revision-f01-f08.md`) | ARG-005, ARG-066 | F1-04b, F09-26 | en desarrollo | `services/api/migrations/0001_core.sql`, `tests/integration/test_journal_pg.py` |
| M-06 | T: fabricar un veredicto | Motor de retos | A2, A8 | Solo el evaluador determinista escribe veredictos, y solo de unidades del plan guardado en campañas en curso con sus compuertas aprobadas; sello v2 que cubre plan y aprobaciones y que la base no deja cambiar | ARG-046 | F05-04, F09-23 | implementada | `tests/architecture/test_verdict_boundary.py`, `tests/integration/test_campaign_integrity.py` |
| M-07 | E: el LLM decide un veredicto | Gateway de IA | A7, A2 | Barrera: ningún import del gateway alcanza el veredicto y el rol de base de datos del gateway no ve los veredictos | ARG-052, ARG-060 | F06-01 | implementada | `tests/architecture/test_ai_boundary.py`, `tests/integration/test_ai_boundary.py` |
| M-08 | T/I: inyección de instrucciones desde los datos | Gateway de IA | A7 | Guardarraíles de entrada y salida sobre texto normalizado (identificadores con separadores, afirmaciones como patrones, escrituras como sentencia), salida JSON forzada, asistente con cuatro herramientas cerradas de solo lectura que no puede dar cifras, citas ni veredictos que sus herramientas no devolvieron, y casos hostiles en los conjuntos dorados | ARG-060, ARG-058 | F06-03, F09-28 | implementada | `services/ai-gateway/argos_ai/guardrails`, `services/ai-gateway/tests/test_hostile_guardrails_pure.py`, `goldens/guardrails/` |
| M-09 | E: el gateway se quita su rol con `RESET ROLE` | Gateway de IA | A2 | Credencial propia del gateway en lugar de `SET ROLE` sobre el superusuario | ARG-052, ARG-085 | F09-04 | en desarrollo | — |
| M-10 | T: borrar o sobrescribir evidencia | WORM | A2, A3 | Object lock en modo conformidad probado con un test, y un cliente del almacén sin método de borrado | ARG-061 | F07-04 | implementada | `tests/integration/test_worm_conformance.py`, `tests/architecture/test_worm_has_no_delete.py` |
| M-11 | T/R: alterar la evidencia después de sellar | Evidencia | A3 | Árbol de Merkle, raíz firmada, sello de tiempo RFC 3161 y anclaje del diario | ARG-063, ARG-064, ARG-065, ARG-066 | F07-06 | implementada | `services/evidence/argos_evidence/merkle.py`, `services/evidence/argos_evidence/signing.py` |
| M-12 | S: falsificar una credencial o su comprobación | Comprobador público | A1 | Credencial VC 2.0 firmada con estado de revocación que caduca; comprobador aislado que ancla el emisor y las raíces de TSA por configuración (nunca del bundle), exige la firma del emisor sobre el expediente y resiste bundles hostiles | ARG-068, ARG-069 | F07-11, F09-20 | implementada | `services/verifier/argos_verifier/checks.py`, `services/verifier/tests/test_verifier.py`, `tests/architecture/test_verifier_isolation.py` |
| M-13 | E: actuar fuera del propio rol | API v1 | A8 | Matriz de autorización versionada, denegación por defecto, roles incompatibles rechazados en toda ruta y separación de deberes por persona en el dominio (nadie aprueba ni confirma lo que pidió) | ARG-072 | F08-02, F09-24 | implementada | `services/api/argos_api/authz/permissions.yaml`, `tests/contract/test_api_authz.py`, `tests/integration/test_separation_of_duties.py` |
| M-14 | R: negar una acción humana | API v1 | A8, A3 | Cada mutación deja su asiento en el diario con la persona detrás (huecos de la revisión F09-02, ver `docs/seguridad/revision-f01-f08.md`) | ARG-071 | F08-03, F09-26 | en desarrollo | `tests/integration/test_api_core.py` |
| M-15 | T: cerrar un hallazgo sin corregirlo | Motor de retos | A8, A3 | Un hallazgo solo se cierra por la reejecución de subsanación; el dominio prohíbe el cierre manual | ARG-048, ARG-049 | F08-06 | implementada | `tests/integration/test_findings.py` |
| M-16 | S: robar la sesión de la consola | Consola | A1 | OIDC con PKCE, token de acceso en memoria y refresco en una cookie de sesión `HttpOnly`, `Secure` y `SameSite=Strict` limitada a `/api/v1/auth`; cierre de sesión que revoca el refresco en el realm; CSP `default-src 'self'; frame-ancestors 'none'`, `nosniff` y `Referrer-Policy` en toda respuesta | ARG-073, ARG-008 | F08-10, F09-30 | implementada | `services/api/argos_api/keycloak.py`, `tests/contract/test_api_session.py`, `services/api/tests/test_api_console_hardening_pure.py`, `console/e2e/logout.spec.ts` |
| M-17 | S: usar una contraseña robada de quien aprueba | Keycloak y API | A1, A8 | Segundo factor TOTP obligatorio para `platform_admin` y `dpo_reviewer`; la API exige `otp` en `amr` | ARG-008, ARG-072 | F09-07 | en desarrollo | — |
| M-18 | S: fuerza bruta contra el inicio de sesión | Keycloak | A1 | Bloqueo temporal por intentos fallidos y política de contraseñas | ARG-008 | F09-07 | en desarrollo | — |
| M-19 | S/T: webhooks falsos o secretos filtrados | Webhooks | A1 | Firma HMAC-SHA256 con marca de tiempo; el secreto va solo a Vault y nunca vuelve en respuestas; destino solo `https` y público, comprobado al suscribir y antes de cada entrega, con la excepción privada escrita por quien instala; la bandeja guarda la clase de error, no su texto | ARG-079 | F08-09, F09-30 | implementada | `services/api/argos_api/webhooks`, `tests/integration/test_api_webhooks.py` |
| M-20 | I: secretos en el repositorio | CI | A5 | gitleaks en cada commit del CI | ARG-010 | — | implementada | `.gitleaks.toml` |
| M-21 | I: un servicio lee las credenciales de un conector | Vault | A2 | Política de Vault exclusiva del SDK de conectores para `argos/data/connectors/*` (P-04) | ARG-009 | F1-05 | implementada | `deploy/dev/vault/setup.sh` |
| M-22 | S/I: suplantar un servicio o escuchar la red interna | Red interna | A1, A2 | mTLS entre servicios con certificados de la PKI de Vault (30 días, rotación automática); PostgreSQL y NATS con TLS | ARG-083 | F09-06 | en desarrollo | — |
| M-23 | S: llamar al gateway de IA haciéndose pasar por otro servicio | Gateway de IA | A2 | Identidad del servicio que llama por mTLS en lugar de un campo del cuerpo | ARG-052, ARG-083 | F09-06 | en desarrollo | — |
| M-24 | E: un contenedor comprometido escala o se mueve | Contenedores | A2 | Usuario sin privilegios, `cap_drop ALL`, raíz de solo lectura, `no-new-privileges` y seccomp; en el compose lo comprueba un test | ARG-084 | F09-03 | en desarrollo | — |
| M-25 | E: desplegar un pod sin postura o una imagen sin firma | k3s | A2, A5 | Admisión con Kyverno (postura y `verifyImages`), perfiles AppArmor | ARG-084, ARG-087 | F09-92 | pendiente de hardware | — |
| M-26 | E/I: una credencial de base de datos robada sirve para todo | PostgreSQL | A2, A3 | Un rol por servicio con mínimo privilegio y credenciales dinámicas de Vault (24 h) | ARG-085 | F09-04, F09-05 | en desarrollo | — |
| M-27 | T: aplicar una actualización manipulada o antigua | Actualizador | A5, A3 | Firma del manifiesto y digests verificados antes de tocar nada, anti-retroceso, aplicación transaccional con plan inverso | ARG-086, ARG-010 | F09-10 | en desarrollo | — |
| M-28 | T: cargar contenido normativo manipulado | Ontología | A5 | Bundle determinista firmado con clave propia, leído en flujo con tope y verificado antes de cargar con la huella fijada y sin retroceso; cada campaña comprueba que el disco del worker y las políticas cargadas en OPA son las firmadas en vigor | ARG-040 | F04-04, F09-25 | implementada | `services/ontology/argos_ontology/bundle.py`, `tests/integration/test_opa_signed_policies.py`, `tests/integration/test_challenge_activities.py` |
| M-29 | T: dependencia o imagen vulnerable o manipulada | CI y release | A5 | Lockfiles, SBOM CycloneDX dentro del manifiesto firmado y puerta de vulnerabilidades con excepciones que caducan | ARG-087 | F09-09 | en desarrollo | — |
| M-30 | E: acceso remoto del soporte | Canal de soporte | A6 | No existe canal remoto; paquete de diagnóstico sin datos de negocio que el operador revisa antes de enviarlo, cifrado para el soporte | ARG-088 | F09-11 | en desarrollo | — |
| M-31 | D: pérdida de datos por borrado, cifrado malicioso o avería | Almacenes | A3 | Backup cifrado de extremo a extremo con prueba de restauración fechada que verifica la cadena del diario | ARG-089 | F09-12 | en desarrollo | — |
| M-32 | T: material que entra o sale por soporte físico | Esclusa | A5, A3 | Importadores que verifican la firma de cada tipo antes de aplicar; exportación de lista cerrada; todo al diario | ARG-090 | F09-13 | en desarrollo | — |
| M-33 | I: leer el disco extraído o arrancar otro sistema | Disco y arranque | A4 | Secure Boot, arranque medido y LUKS2 sellado al TPM (PCR 7+11) con recuperación en sobre | ARG-082 | F09-91 | pendiente de hardware | — |
| M-34 | I: extraer las claves de firma | Claves | A4, A3 | Claves en TPM no exportables (hoy, Vault transit no exportable y marcado `non_production`) | ARG-064, ARG-082 | F07-15, F09-91 | pendiente de hardware | — |
| M-35 | T: el root del sistema de ficheros toca los objetos del WORM | WORM | A3 | Cifrado del volumen y endurecimiento del sistema operativo; auditd sobre las rutas de claves | ARG-061, ARG-081, ARG-082 | F1-11a, F09-91 | pendiente de hardware | — |
| M-36 | E: superficie del sistema operativo | Sistema operativo | A1, A3 | Imagen endurecida con el perfil CIS Level 1 (umbral 90 %), SSH solo con llave y auditd | ARG-081 | F09-14, F09-90 | pendiente de hardware | — |
| M-37 | R: actividad maliciosa que nadie ve | Toda la plataforma | A1, A3, A8 | Registro de seguridad separado y encadenado (autenticación, denegaciones, administración, actualizaciones, esclusa) con alertas | ARG-005, ARG-072 | F09-08 | en desarrollo | — |
| M-38 | D/T: consultas abusivas a la API del grafo | API GraphQL | A1, A8 | Etiquetas en lista blanca, prefijos acotados, paginación y profundidad máxima 4 | ARG-029 | F03-12 | implementada | `services/inventory/argos_inventory/api/schema.py`, `services/inventory/tests/test_api_http.py` |
| M-39 | I/T: tráfico en claro hacia los sistemas del cliente | Conectores | A1 | Transporte cifrado y verificado obligatorio en SQL, ficheros, LDAPS, REST, FHIR y DICOM, salvo declaración explícita por sistema (auditoría del 2026-09-18, integrada en F09-17); SQL Server solo cuenta como cifrado con ODBC Driver 18 verificando | ARG-014, ARG-017, ARG-018, ARG-019, ARG-020 | F09-17, F09-31 | implementada | `connectors/sdk/tests/test_sdk_tls.py`, `connectors/sql/tests/test_sql_generic.py`, `connectors/rest/tests/test_rest_connector.py` |
| M-40 | I: el material público revela algo que no debe | `evidence-api` y comprobador | A1 | Solo sirven material público; la credencial no lleva datos personales (lo comprueba un test con los validadores de ARG-024) | ARG-068, ARG-069 | F07-10 | implementada | `tests/integration/test_credential.py` |

## 6. Qué cambia al pasar al appliance

- La **firma** pasa de Vault transit a TPM (`F07-15`, `F09-91`). Mientras tanto la evidencia lleva la marca `non_production`.
- La **admisión** pasa de un test sobre el compose a Kyverno en k3s (`F09-92`).
- La **identidad de servicio** en Vault pasa de AppRole a cuentas de servicio de Kubernetes (`F09-92`).
- El **sello de tiempo** pasa de la TSA de desarrollo a una TSA cualificada (`F07-16`).

## 7. Riesgos residuales

| Riesgo | Por qué queda | Quién lo acepta |
|---|---|---|
| Un administrador con root y acceso físico al appliance encendido puede leer datos en claro de la memoria o del volumen abierto | Es inherente a un equipo en la sala del cliente; el cifrado protege el disco apagado o extraído | El organismo, en su declaración de aplicabilidad (medidas físicas y de personal) |
| El LLM puede dar respuestas equivocadas en el asistente o en los dictámenes | Ningún modelo es infalible; por eso no decide veredictos (M-07) y sus textos llevan la marca de texto asistido | Nosotros, con la barrera y los conjuntos dorados como puerta de release |
| Hasta que llegue el hardware, firma, sello y almacén son de desarrollo | Faltan TPM, TSA cualificada y LUKS | Nosotros, declarado como `non_production` en toda la evidencia |
| La disponibilidad depende de un solo nodo en la talla S | Decisión de producto (Especificación §3.9) | El organismo, al elegir la talla |
| Una vulnerabilidad sin corrección publicada en una dependencia | No siempre hay parche | Nosotros, con excepción justificada y con caducidad (F09-09) |

## 8. Historial

| Versión | Fecha | Cambio |
|---|---|---|
| 1.0 | 2026-09-23 | Primera versión (F09-01) |
| 1.1 | 2026-09-23 | M-39 pasa a implementada al integrar la auditoría del 2026-09-18 (F09-17) |
| 1.2 | 2026-09-23 | M-01, M-03, M-05, M-06, M-12, M-13, M-14 y M-28 vuelven a «en desarrollo» por los huecos que encontró la revisión F09-02, con su tarea de corrección |
| 1.3 | 2026-09-23 | M-12 vuelve a «implementada» tras F09-20 |
| 1.4 | 2026-09-23 | M-01 vuelve a «implementada» tras F09-21 |
| 1.5 | 2026-09-23 | M-03 vuelve a «implementada» y M-02 cubre la exploración y las peticiones adicionales tras F09-22 |
| 1.6 | 2026-09-23 | M-06 vuelve a «implementada» tras F09-23 |
| 1.7 | 2026-09-23 | M-13 vuelve a «implementada» tras F09-24 |
| 1.8 | 2026-09-23 | M-28 vuelve a «implementada» tras F09-25 |
| 1.9 | 2026-09-23 | M-08 recoge los guardarraíles normalizados y las cifras con respaldo de F09-28 |
| 1.10 | 2026-09-23 | M-16 y M-19 recogen el cierre de sesión, las cabeceras y los webhooks sin destinos internos de F09-30 |
| 1.11 | 2026-09-23 | M-04 y M-39 recogen la minimización de `check_config`, SQL Server verificado y DICOM con TLS de F09-31 |
