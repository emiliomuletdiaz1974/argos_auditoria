---
id: MOD-argos-airgap
kind: module
title: Esclusa de soportes (argos-airgap)
module: argos-airgap
phases: ["09"]
version: 0.1.0-alpha
commit: pendiente
date: 2026-09-24
status: current
confidentiality: client
---

# Esclusa de soportes (argos-airgap)

## 1. Propósito

El appliance aislado no tiene salida a Internet (Pliego P-02). **Todo lo que entra y todo lo que sale pasa por una sola puerta formal**, en soporte extraíble:

- lo que entra se verifica con su propia firma antes de aplicar nada;
- lo que sale pertenece a una lista cerrada de tipos;
- cada fichero y cada exportación, aceptados o no, quedan en el diario y en el registro de seguridad.

Implementa ARG-090 (tarea F09-13; Pliego P-02; nota de desviación ARG-081-090).

## 2. Alcance y límites

- **Entra:**
  - paquetes de actualización (`argos-update-<versión>.tar`, ARG-086);
  - paquetes de contenido normativo (`argos-ontology-<versión>.tar.gz` con su `.sig`, ARG-040);
  - respuestas de sello de tiempo (`<32 hex>.tsr`, ARG-065).
- **Sale (lista cerrada):**
  - peticiones de sello (`.tsq`);
  - el paquete de diagnóstico revisado (ARG-088);
  - el expediente de una campaña;
  - su credencial.
- **Fuera de este módulo:**
  - montar el dispositivo en solo lectura y remontarlo para escribir solo durante una exportación: es del appliance (udev, F09-92);
  - aplicar la actualización: es del actualizador, que vuelve a verificarla.

## 3. Arquitectura

- **`Gate.scan(actor)`** recorre el soporte. Para cada entrada:
  1. la reconoce solo si su nombre encaja entero en el patrón de un tipo (`IMPORT_RULES`);
  2. la rechaza **sin leerla** si no es un fichero normal: un enlace simbólico, una carpeta o un dispositivo;
  3. la rechaza si supera el tamaño de su tipo;
  4. la copia a una zona de trabajo calculando su SHA-256, y se detiene si crece por encima del límite mientras se lee;
  5. se la entrega al importador de su tipo.

  La zona de trabajo se vacía después de cada fichero y el soporte nunca se modifica.
- **Importadores** (`argos_airgap.importers`):
  - `update_importer`:
    - desempaqueta con el filtro `data` de `tarfile` (sin rutas absolutas, sin `..`, sin enlaces hacia fuera, sin dispositivos);
    - verifica con **el mismo** `verify_bundle` del actualizador (F09-10);
    - deja el paquete en su bandeja y la petición en su cola, como `POST /api/v1/system/updates`.
  - `content_importer`: `load_bundle` de ARG-040 (huella fijada, firma, sin retroceso), que solo entonces guarda la versión.
  - `tsr_importer`:
    - asocia cada respuesta con el objeto en cola cuyo nombre lleva (`tsr_name`);
    - la verifica con `accept_reply`: estado, cadena a una raíz de confianza, nonce y SHA-256 del objeto guardado.
- **`Gate.export(kind, actor, params)`:**
  - `kind` debe estar en `EXPORT_KINDS`, una **constante** (`frozenset`), no configuración: cualquier otro tipo es un `PermissionError` y queda registrado;
  - una esclusa no puede construirse con un exportador fuera de la lista;
  - cada exportación va a una carpeta nueva del soporte, con el tamaño y el SHA-256 de cada fichero.
- **Exportadores** (`argos_airgap.exporters`):
  - `tsq`: `export_requests`;
  - `dossier` y `credential`: leídos del WORM y comprobados contra la huella con la que se registraron;
  - `diagnostics`: `build_package` solo para el índice aprobado.
- **`recorder(dsn)`:** cada operación va al diario (con su resultado) y al registro de seguridad (`source=argos-airgap`).

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Constante | `EXPORT_KINDS` | `tsq`, `diagnostics`, `dossier`, `credential`: lo único que puede salir |
| Constante | `IMPORT_RULES` | Patrón de nombre, tamaño máximo y fichero acompañante de cada tipo que entra |
| Clase | `Gate(inbox, outbox, work, importers, exporters, record)` | `scan(actor)` e `export(kind, actor, params)` |
| Función | `check_name(name) -> str \| None` | El tipo de un nombre, o nada |
| Función | `tsr_name(object_key)` | El nombre de la petición y de la respuesta de un objeto |
| Función | `recorder(dsn)` | Diario y registro de seguridad |
| API | `POST /api/v1/airgap/imports` (`airgap.import`, con segundo factor) | Lee el soporte e importa lo que verifica; devuelve fichero, tipo, resultado, motivo y SHA-256 |
| API | `POST /api/v1/airgap/exports` (`airgap.export`, con segundo factor) | Escribe un tipo de la lista (`kind`, y `campaign_id` o `diagnostics_id` y `approved_index_sha256`); `403` fuera de la lista |
| Consola | Sección «Esclusa» | Resultado de cada fichero que entra, y un selector limitado a la lista cerrada para lo que sale |

## 5. Configuración

- **API:**
  - `ARGOS_AIRGAP_DIR`: con `in/` (montado en solo lectura), `out/` y `work/`;
  - `ARGOS_CONTENT_PUBLIC_KEY_FILE`: la clave de contenido fijada, cuya huella se exige al cargar.

  Sin la carpeta no hay esclusa (`503`). Cada importador y exportador existe solo si su servicio está configurado: actualizaciones, evidencia, diagnóstico y clave de contenido.
- **Desarrollo:** `tools/dev_airgap.py` prepara `deploy/dev/airgap/` (ignorado por git) en cada `make dev` y toma la clave de contenido de Vault transit (`argos-content`).
- **Base de datos:** la migración 0038 permite a `svc_api` insertar las cuádruplas de una versión de contenido verificada. No puede actualizar ni borrar.

## 6. Seguridad y tratamiento de datos

- **Nada se aplica sin verificar, y siempre con la verificación de su dominio.** El importador de actualización usa la misma función que el actualizador, y un test comprueba que es el mismo objeto. El actualizador vuelve a verificar al aplicar.
- **El soporte no se sigue:**
  - los enlaces, las carpetas y los dispositivos se rechazan sin abrirlos;
  - un archivo que intente escribir fuera de su carpeta se rechaza;
  - el soporte nunca se modifica.
- **La lista de lo que sale es código, no configuración.** Añadir un tipo exige cambiar la constante y su test.
- **Solo el administrador de la plataforma, con segundo factor.** Lo que entra puede cambiar el appliance y lo que sale lo abandona.
- **Todo queda registrado.** Cada fichero y cada exportación, aceptados o rechazados, llevan actor, fichero, tipo, tamaño, SHA-256, resultado y motivo. Una exportación registra cuántos ficheros salieron y la huella de su lista.

## 7. Operación

- **Actualizar un appliance aislado:** el paquete llega en el soporte → «Esclusa» → «Leer el soporte» → el actualizador lo aplica (`argos-update watch`).
- **Sellado aislado:**
  1. «Salida» → peticiones de sello;
  2. se sellan fuera con una TSA;
  3. las respuestas `.tsr` vuelven con el mismo nombre;
  4. «Leer el soporte».
- **Entregar un expediente, una credencial o un diagnóstico:** «Salida» con el tipo y su campaña, o su paquete revisado.

## 8. Verificación

- **`services/airgap/tests/test_gate_pure.py`:**
  - la lista de exportaciones es una constante cerrada;
  - un tipo fuera de ella se rechaza y se registra, y ninguna esclusa se construye con él;
  - los nombres con `../`, las barras y los ficheros ocultos se rechazan;
  - un enlace simbólico se rechaza sin leerlo;
  - las carpetas y los ficheros desconocidos se rechazan;
  - el límite de tamaño;
  - un `.tsr` con firma inválida se rechaza, se registra y no se aplica;
  - un paquete de actualización sin firma se rechaza por el mismo `verify_bundle` del actualizador;
  - uno firmado queda en cola;
  - un archivo que escapa de su carpeta se rechaza;
  - la zona de trabajo se vacía.
- **`services/api/tests/test_airgap_routes.py`:** importación y exportación, `403` fuera de la lista, segundo factor y solo `platform_admin`.
- **`tests/integration/test_airgap.py`**, contra el entorno de desarrollo:
  - ciclo completo del sellado aislado: exportar `.tsq`, sellar con la TSA de desarrollo e importar el `.tsr`, que queda sellado; una respuesta que nadie pidió se rechaza;
  - un expediente y su credencial reales salen comprobados contra su huella;
  - asientos en el diario y eventos en el registro de seguridad;
  - la ruta desplegada exige token.
- **`console/src/views/airgap/airgap.test.tsx`:** resultado por fichero, selector limitado a la lista cerrada, exportación y rechazo explicado.

## 9. Limitaciones conocidas y pendientes

- **El remontaje del soporte** (solo lectura, y escritura solo durante una exportación) es del appliance (F09-92). En desarrollo, `in/` se monta en solo lectura y `out/` es otra carpeta.
- **La importación de contenido no tiene prueba de integración propia**: `load_bundle` ya la tiene en ARG-040, y aquí se cablea con la clave fijada.
- **La exportación de diagnóstico se prueba en la ruta pura, sin un paquete real.** El paquete real lo prueba F09-11.
- **El realm de desarrollo no tiene usuario `platform_admin`**: la ruta desplegada solo se prueba cerrada.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-24 | Esclusa con importadores verificados (actualización, contenido, sellos), exportación de lista cerrada (peticiones de sello, diagnóstico, expediente, credencial), registro de cada operación, API y consola | F09-13 (ARG-090) |
