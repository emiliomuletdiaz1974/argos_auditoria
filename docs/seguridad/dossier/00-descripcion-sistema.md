# Descripción del sistema

**Versión:** 1.0 · **Fecha:** 2026-09-24 · **Dossier de seguridad v1** · **Confidencialidad:** `client`

## 1. Qué es ARGOS

ARGOS es un sistema de verificación activa del cumplimiento (RGPD, EHDS, AI Act y ENS) que se instala en las instalaciones del organismo, sobre un equipo propio: el appliance.

1. **Inventario:** descubre los sistemas de información del organismo y clasifica sus datos.
2. **Retos:** reta esos sistemas con comprobaciones de solo lectura derivadas de la norma.
3. **Veredicto:** decide cada reto con un evaluador determinista.
4. **Evidencia:** acredita el resultado con un expediente sellado y una credencial verificable.

Nada sale del perímetro del organismo salvo lo que el operador exporta por la esclusa.

## 2. Arquitectura

| Capa | Componentes | Documento técnico |
|---|---|---|
| Acceso | API única v1 (`argos-api`) y consola servida desde su mismo origen; Keycloak como proveedor de identidad | `docs/tecnica/modulos/argos-api.md`, `argos-console.md`, `argos-auth.md` |
| Conectores | SQL, PostgreSQL, Oracle, SQL Server, ficheros, LDAP, REST, FHIR y DICOM, todos de solo lectura, con diario previo de cada consulta y presupuesto de carga | `docs/tecnica/modulos/argos-connector-*.md` |
| Núcleo | Inventario y grafo (PostgreSQL con Apache AGE), ontología normativa, motor de retos (Temporal) y evaluador determinista | `argos-inventory.md`, `argos-ontology.md`, `argos-challenge-engine.md` |
| IA local | Gateway de IA con guardarraíles; el modelo nunca decide un veredicto | `argos-ai-gateway.md` |
| Evidencia | Almacén WORM, árbol de Merkle, firma, sellado temporal RFC 3161, expediente, credencial y comprobador público | `argos-evidence.md`, `argos-verifier.md` |
| Plataforma | Diario encadenado, registro de seguridad, Vault (secretos, PKI interna, credenciales dinámicas de base de datos), mTLS interno, actualizador firmado, paquete de diagnóstico, esclusa de soportes y backup | `argos-common.md`, `argos-tls.md`, `argos-updater.md`, `argos-support.md`, `argos-airgap.md` |

Las decisiones de arquitectura están en `docs/adr/`, y ADR-0014 recoge la seguridad de plataforma. Cada decisión está registrada con su motivo en `docs/decisiones/`.

## 3. Flujos de datos

1. **Descubrimiento:**
   - los conectores leen metadatos y muestras acotadas de los sistemas del organismo;
   - a la plataforma solo llegan tasas de aceptación de validadores y resúmenes minimizados, nunca los valores.
2. **Retos:**
   - el motor compila la campaña sobre una instantánea del inventario, y dos personas distintas aprueban las compuertas;
   - las sondas, siempre de solo lectura, quedan en el diario antes de ejecutarse;
   - el evaluador decide sin modelo de lenguaje.
3. **Evidencia:**
   - cada veredicto es un artefacto en el WORM;
   - la raíz de la campaña se firma y se sella en el tiempo;
   - el expediente y la credencial se verifican fuera de ARGOS con el comprobador público.
4. **Entrada y salida del appliance:**
   - las actualizaciones, el contenido normativo y los sellos entran por la esclusa, verificados con su firma;
   - las peticiones de sello, el diagnóstico, los expedientes y las credenciales salen por la misma esclusa, de una lista cerrada.

## 4. Fronteras de confianza

Descritas con sus amenazas y mitigaciones en el [modelo de amenazas](../modelo-amenazas.md).

- **Red del organismo ↔ appliance:**
  - solo la API y la consola están expuestas;
  - autenticación OIDC y segundo factor para los roles que deciden;
  - el mismo origen para toda mutación.
- **Entre servicios del appliance:** mTLS con certificados de la PKI interna, y un rol de base de datos por servicio con credenciales dinámicas.
- **Appliance ↔ sistemas del organismo:** conectores de solo lectura, validadores de sentencias por dialecto y TLS verificado.
- **Capa de IA ↔ veredicto:** barrera arquitectónica comprobada por tests. Ningún camino lleva del modelo a un veredicto.
- **Appliance ↔ exterior:** sin red. Solo la esclusa de soportes, con verificación de firma a la entrada y lista cerrada a la salida.

## 5. Qué está probado y dónde

- **Todo lo marcado como implementado** está en `main` y tiene evidencia enlazada: un test, una configuración o un informe.
- **El entorno de las pruebas es el de desarrollo** (Docker Compose), no el appliance. Lo que depende del despliegue se marca «implementada en desarrollo». Lo que necesita el equipo físico (TPM, Secure Boot, imagen endurecida, k3s) se marca «pendiente de hardware», con su tarea.
- **Evidencias generadas:**
  - la [batería de accesos indebidos](../bateria-accesos.md), contra la API desplegada;
  - la [revisión de seguridad de F1–F8](../revision-f01-f08.md);
  - la [prueba de restauración del backup](../backup-restauracion.md);
  - el [endurecimiento de la imagen](../endurecimiento-imagen.md).
