# ADR-0014 · Seguridad de plataforma sin appliance: qué se construye ya y qué espera al hardware

- **Estado:** Propuesta
- **Fecha:** 2026-09-23
- **Decide:** el usuario (tarea F09-00)
- **Contexto:** Fase 09 · Seguridad de plataforma (ARG-081…ARG-090) · Pliego P-02, P-06, P-22, P-23, P-25 · Plan Director §8.2 «Fase 09», §13 y §14 · Especificación Técnica §3.8

## Contexto

El documento de la Fase 09 describe la seguridad del appliance sobre tres cosas que todavía no existen: la imagen Packer con Ubuntu 24.04 (ARG-002), el clúster k3s (ARG-003) y un TPM 2.0 con Secure Boot. Las tres están aplazadas desde ADR-0001 a la llegada del Servidor Cognitivo (tareas MANUAL `F1-11a` y `F1-11b`). Todo lo construido hasta la Fase 08 corre en Docker Compose (`deploy/dev/`).

Mirando el repositorio antes de decidir:

- Todos los servicios se conectan a PostgreSQL como el mismo usuario `argos`, con `POSTGRES_HOST_AUTH_METHOD: trust`. El único rol restringido es `argos_ai` (migración `0015`), que sostiene la barrera del veredicto de la Fase 06.
- Ningún contenedor declara usuario, `cap_drop`, `read_only` ni `no-new-privileges`.
- El realm de Keycloak no exige segundo factor a nadie.
- Vault ya tiene PKI raíz e intermedia (`pki`, `pki_int`, rol `argos-svc` de 720 h), pero nadie le pide certificados: el tránsito interno va en claro.
- El manifiesto de release se firma con Ed25519 en Vault transit (nota ARG-010); no hay registro de imágenes ni cosign.
- El Plan Director pide dos cosas que el documento de fase no desarrolla: **MFA** en la consola y un **registro de seguridad separado del diario funcional**, con sus alertas.

Esperar al hardware para toda la fase dejaría sin hacer justo lo que no depende de él —y lo que la revisión de seguridad va a encontrar primero—.

## Decisión

1. **Tres niveles, declarados por tarea.**
   - **Se construye y se prueba ya en el compose:** postura de contenedores, roles de base de datos por servicio, credenciales dinámicas, mTLS, MFA, registro de seguridad, SBOM y puerta de vulnerabilidades, actualizador transaccional, paquete de diagnóstico, backup con prueba de restauración y esclusa de soportes.
   - **Se escribe ya y se valida en estático:** los manifiestos de k3s (`platform/k8s/security/`: `ClusterIssuer` y `Certificate` de cert-manager, las `ClusterPolicy` de Kyverno, perfiles seccomp y AppArmor) y `platform/image/harden.sh` con `hardening-exceptions.yaml`. Tests que cargan el YAML y comprueban las invariantes (todo namespace `argos-*` cubierto, `Enforce` y no `Audit`, ninguna excepción sin justificación ni caducidad) y una ejecución de `harden.sh` dos veces en un contenedor `ubuntu:24.04` para probar que es idempotente.
   - **Espera al hardware (tareas MANUAL):** la puntuación CIS real de la imagen, Secure Boot, arranque medido, LUKS2 sellado a PCR 7+11 con resellado tras actualizar, el ciclo de vida de claves en TPM (junto con `F07-15`), y aplicar en k3s cert-manager, Kyverno, AppArmor y la verificación de firmas de imagen en admisión.
2. **La admisión en el compose es un test.** No hay controlador de admisión en Docker Compose. El equivalente de la `ClusterPolicy` `argos-pod-baseline` es un test que recorre `deploy/dev/compose.yaml` y falla si un servicio de ARGOS no declara usuario sin privilegios, `cap_drop: [ALL]`, sistema de ficheros raíz de solo lectura, `no-new-privileges` y perfil seccomp; y otro de integración que comprueba dentro de los contenedores levantados que el proceso no es root y no puede escribir fuera de sus volúmenes. Las imágenes de terceros (PostgreSQL, Vault, Keycloak…) entran con las excepciones que necesiten, escritas y justificadas en el propio test. AppArmor no se puede probar en el Docker de Windows (la máquina virtual de Docker Desktop no lo carga): sus perfiles se escriben y se aplican en k3s.
3. **Un rol de PostgreSQL por servicio, con credenciales dinámicas de Vault.** Migración con los roles base `svc_<servicio>` y solo los permisos que cada servicio usa; autenticación `scram-sha-256` en lugar de `trust`; el motor `database` de Vault crea usuarios efímeros miembros de esos roles (TTL 24 h, máximo 72 h). En el compose los servicios se autentican en Vault con **AppRole** (no hay cuentas de servicio de Kubernetes); en k3s será el método `kubernetes`, detrás de la misma función. El pool se reconstruye en caliente al renovar (`argos_common.dynamic_db`).
4. **mTLS con la PKI de Vault que ya existe.** Nueva librería `libs/tls` (paquete `argos_tls`) con el contexto que se recarga al rotar y el cliente `httpx` con certificado. En el compose un servicio `cert-issuer` pide a `pki_int` un certificado por servicio (30 días, renovado a los 20) y lo deja en un volumen; en k3s lo hará cert-manager. Alcance: las llamadas HTTP entre servicios de ARGOS, PostgreSQL (`hostssl` con verificación del certificado de servidor) y NATS. Temporal y Keycloak internos se cifran en k3s y quedan anotados en la nota ARG-081-090.
5. **Una sola firma: la de release en Vault transit.** El actualizador verifica la firma Ed25519 del manifiesto y los digests de todo lo que el manifiesto lista antes de tocar nada. El **SBOM** (CycloneDX, generado con syft) y el informe de vulnerabilidades (grype) no se firman por separado: su SHA-256 entra en el manifiesto firmado, así que viajan firmados con él. cosign y la verificación de imágenes en admisión llegan con el registro local del appliance, como ya decía la nota ARG-010.
6. **Herramientas externas como imágenes fijadas por digest.** syft, grype y restic se ejecutan con `docker run` sobre imágenes fijadas por digest: no hay que instalar nada en la máquina de trabajo y el CI usa las mismas. El cifrado del paquete de diagnóstico usa `age` a través de `pyrage`, que es una dependencia Python con *lockfile*.
7. **Registro de seguridad separado: tabla encadenada propia.** Esquema `security` con la tabla `security.events` (fallos de autenticación, denegaciones de autorización, uso de permisos de administración, actualizaciones, operaciones de la esclusa, pruebas de restauración) encadenada con el mismo algoritmo que el diario v1 (ADR-0002) pero en **su propia cadena**, escrita por un rol que el resto de servicios no tiene, y con reglas de alerta en Prometheus (ráfaga de 401/403, cadena rota, prueba de restauración caducada). El diario funcional sigue contando qué hizo el producto; el de seguridad, quién intentó qué.
8. **MFA con TOTP para los roles que deciden.** El realm exige segundo factor a `platform_admin` y `dpo_reviewer`; el token lleva `amr` y la API rechaza con `401` las rutas de esos permisos si falta `otp`. `campaign_manager` y `read_only_auditor` quedan con el primer factor en desarrollo y el cliente decide en la implantación.
9. **El dossier se escribe contra ENS categoría media y ISO/IEC 27001:2022.** `docs/seguridad/`: modelo de amenazas, revisión de F1–F8, y una tabla por medida del Anexo II del ENS (RD 311/2022) y por control del Anexo A de la ISO 27001 con su estado (implementado, implementado en desarrollo, pendiente de hardware, del organismo) y el enlace a su evidencia en el repositorio. Se empaqueta con `tools/docs_pack.py`. Entregarlo a la consultora es una tarea DECISIÓN.
10. **La prueba de la fase no espera al hardware.** `F09-99` cierra con la batería de accesos indebidos, la restauración completa en entorno limpio con verificación de la cadena del diario, la actualización sin firma rechazada y el dossier v1 listo. Las tareas con hardware quedan como MANUAL y no bloquean el tag `fase-09`, igual que `F02-98` o `F08-98`.

## Consecuencias

- Los servicios dejan de conectarse como superusuario: la migración de roles es transversal y rompe cualquier consulta que hoy toque tablas de otro servicio. Es lo que se quiere encontrar, y por eso va pronto en la fase.
- El compose gana dos servicios (`cert-issuer` y el contenedor del actualizador) y todos los de ARGOS cambian de usuario y de sistema de ficheros: los que escriben en disco necesitan su volumen declarado.
- El dossier dirá con claridad qué controles solo existen en desarrollo. Es incómodo, pero es lo que un auditor ENS pregunta primero.

## Alternativas descartadas

- **Esperar al hardware para toda la fase:** deja sin hacer lo que no depende de él (roles de base de datos, MFA, postura de contenedores, backup) y retrasa la revisión de seguridad, que es la que va a encontrar los fallos reales.
- **Montar k3s en una máquina virtual ahora:** da Kyverno y cert-manager, pero no TPM ni arranque medido, y duplica el entorno de desarrollo que la Fase 10 tendrá que reconstruir en el appliance. ADR-0001 ya lo descartó por el mismo motivo.
- **cosign ya, con un registro local en el compose:** añade un registro y una segunda firma solo para desarrollo; la firma del manifiesto ya cubre el digest de cada imagen.
- **Registro de seguridad como flujo de logs en Loki:** más ligero, pero un log no se puede verificar como una cadena y el auditor ENS pide integridad del registro de actividad (medida op.exp.8).
