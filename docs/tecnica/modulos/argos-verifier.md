---
id: MOD-argos-verifier
kind: module
title: Comprobador público de evidencias (argos-verifier)
module: argos-verifier
phases: ["07"]
version: 0.6.0-alpha
commit: 7cea717
date: 2026-10-08
status: current
confidentiality: client
---

# Comprobador público de evidencias (argos-verifier)

## 1. Propósito

Permite a un tercero sin cuenta en ARGOS (un auditor, un inspector, la otra parte de un contrato) comprobar que un expediente de campaña es íntegro y está firmado, sellado en el tiempo y respaldado por una credencial vigente. Solo necesita lo que se le entrega y lo que es público. Implementa ARG-069 (pliego P-18).

Además sirve el **catálogo normativo**: el espacio de nombres `https://ns.argos.eu/norms/`, para que las IRI con que los hallazgos y la evidencia citan cada obligación se puedan abrir (nota de desviación ARG-069).

## 2. Alcance y límites

- **Hace:** comprobar un **paquete de verificación** pieza a pieza y decir, para cada comprobación, si pasó, si falló y por qué, o si no se pudo hacer.
- **Hace también:** servir, solo lectura y sin credenciales, cada norma, artículo, obligación y clase de activo de la población que lleva su imagen, como página, Turtle o JSON-LD, y el catálogo entero en Markdown y PDF.
- **No hace:** no consulta la base de datos, el almacén WORM ni ningún servicio de la plataforma; no guarda lo que recibe; no emite ni revoca nada.

## 3. Arquitectura

- `argos_verifier.checks`: `verify_bundle(bundle) -> Report`. Cada comprobación tiene nombre, estado (`passed`, `failed`, `skipped`) y detalle. Un paquete mal formado da una comprobación fallida con su explicación, nunca una excepción.
- `argos_verifier.api`: FastAPI, `POST /verify`, `GET /verify` (la página que abre el QR de un expediente impreso) y `GET /health`, sin documentación interactiva expuesta.
- `argos_verifier.norms`: lee una vez la población de `library/ontology` (núcleo, normas, obligaciones generadas y clases de activo) con `rdflib`, arma el catálogo (`catalogue()`) y lo presenta: `front_page()`, `page()` por nodo, `description()` en RDF, `markdown()` y `pdf()` (con `reportlab`, como el expediente). Las páginas enlazan por ruta (`/norms/…`), así que sirven igual con el nombre del banco y con `ns.argos.eu`.
- `tools/verify_evidence.py`: la misma comprobación por línea de órdenes y sin red. Código de salida 0 si nada falla, 1 si algo falla y 2 si el paquete no se puede leer.
- Usa **solo el núcleo puro de verificación** de `argos-evidence` (`argos_evidence.core`, `argos_evidence.merkle` y los módulos puros de `argos_evidence.credential`). Un test arquitectónico importa el comprobador en un intérprete limpio y falla si se carga el cliente de PostgreSQL, el de S3, el de Vault, NATS, Temporal o cualquier módulo de la plataforma con E/S.

### Qué se comprueba

| Comprobación | Qué significa |
|---|---|
| `dossier_hash` | El expediente coincide con su propio SHA-256 |
| `issuer_key` | El documento DID del emisor publica una clave de aserción |
| `root_signature` | El sobre de la raíz de campaña está firmado con esa clave (avisa si es una clave de desarrollo) |
| `root_matches_dossier` | La raíz firmada, la campaña y el sobre son los que cita el expediente |
| `timestamp` | El token RFC 3161 cubre ese sobre y encadena con una raíz de TSA de confianza; «skipped» si el sello sigue en cola |
| `credential` | La credencial verifica contra el DID y su bit de la lista de estado no está levantado |
| `credential_matches_dossier` | La credencial respalda este expediente y no otro |
| `artifact_inclusion[i]` | Cada artefacto entregado coincide con su hash y es la hoja indicada del árbol de la campaña |

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Función pública | `checks.verify_bundle(bundle) -> Report` | `Report.ok` y `Report.as_dict()` con cada comprobación |
| API | `POST /verify` (`application/json`, máximo 16 MiB), `GET /health` | Devuelve el mismo informe que la función |
| API pública | `GET /verify?dossier=<SHA-256>` | Página que abre el QR del expediente: qué expediente es y cómo comprobarlo. `400` si el código no es un SHA-256, sin repetirlo |
| API pública | `GET /norms/`, `GET /norms/{nombre}` (HTML; `text/turtle` o `application/ld+json` por `Accept`), `GET /norms/catalogo.md`, `GET /norms/catalogo.pdf` | Catálogo normativo. `404` si el nombre no está en el espacio de nombres; el nombre se valida antes de buscarlo y nunca llega a una ruta de fichero |
| Herramienta de línea de órdenes | `tools/verify_evidence.py <paquete.json> [--json informe.json]` | Informe legible y, si se pide, en JSON |
| Formato | `argos/verification-bundle/1` | JSON con el expediente, el sobre firmado, el token y cada artefacto en base64 (bytes exactos), la credencial, el documento DID, la lista de estado y las raíces de TSA. Lo produce `argos_evidence.bundle.export_bundle` |
| Servicio del entorno | `verifier` (`127.0.0.1:8007`, red propia `verifier`) | Contenedor sin acceso a ningún otro servicio |

## 5. Configuración

Ninguna de la plataforma. `ARGOS_API_BIND` solo indica en qué dirección escucha dentro del contenedor. `ARGOS_ONTOLOGY_DIR` cambia de dónde lee la población (por defecto, `library/ontology` de la imagen).

## 6. Seguridad y tratamiento de datos

- **Siempre un informe (QA-052):** artefactos, cadena de evidencia o Merkle de un tipo inesperado dan una comprobación fallida, nunca un 500.
- **Sin mapa de rutas** (F09-15, SEC-059): el comprobador no sirve `/openapi.json` ni `/docs`; publica sus rutas, no su descripción, como el servicio de evidencia y la API fuera de desarrollo.
- **Postura del contenedor** (F09-03, ARG-084, P-22): corre como `10001:10001`, sin capacidades (`cap_drop: [ALL]`), con la raíz de solo lectura y `/tmp` en `tmpfs`, sin escalada (`no-new-privileges`) y con el perfil seccomp por defecto de Docker. La imagen no lleva `bash`. En el compose lo exige `tests/security/test_compose_posture.py`, y `tests/integration/test_container_posture.py` lo comprueba dentro del contenedor en marcha.
- **Catálogo normativo** (nota ARG-069): público por diseño; solo publica lo que ya está en el repositorio. Cada página avisa de que el contenido está pendiente de validación jurídica. Sin scripts: `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'`, `nosniff` y `Referrer-Policy: no-referrer`. Todo lo que viene del contenido se escapa. En el banco se publican `/norms/` y `/verify` (`ns.<ip>.sslip.io`), donde apunta el QR de los expedientes.
- Sin estado: nada de lo recibido se guarda. El registro anota solo el SHA-256 del paquete y el resultado.
- El cuerpo de la petición está limitado a 16 MiB y se rechaza antes de leerse si su longitud declarada lo supera.
- La confianza parte de dos anclas explícitas: el documento DID del emisor y las raíces de la TSA. El comprobador no descarga nada por su cuenta; quien lo usa decide de dónde obtiene esas anclas.
- Decisiones aplicables: ADR-0011 (credencial), nota ARG-064-065 (firma y TSA de desarrollo, que el informe señala como tales).
- **La confianza no viaja en el bundle** (SEC-001, F09-20): `verify_bundle(bundle, trust, at=…)` recibe una `Trust` con las huellas de las claves de emisor (`key_id`, SHA-256 truncado de la clave pública) y las raíces de TSA en que se cree. El contenedor la lee en cada petición de `ARGOS_VERIFIER_TRUST_FILE` (en desarrollo, `deploy/dev/verifier/trust.json`, que escribe `tools/verifier_trust.py` en `make dev`); el CLI, de `--trust`. Sin anclaje, el emisor queda «no anclado» y nada verifica. Las `tsa_roots` del bundle se ignoran.
- **El contenido del expediente tiene que estar firmado** (SEC-002): la comprobación `dossier_authenticated` exige la credencial del emisor de confianza sobre el SHA-256 del expediente (aunque esté revocada, la firma sigue diciendo quién lo afirmó); sin ella el informe no es `ok`.
- **Bundles hostiles** (SEC-003): el cuerpo se lee por partes con tope de 16 MiB aunque llegue *chunked*; los valores base58 de más de 128 caracteres se rechazan antes de decodificar; la lista de estado se descomprime con techo.
- **Revocación con frescura** (SEC-018): una lista de estado sin `validUntil` o caducada a la fecha `at` no prueba nada; `--at` permite comprobar un paquete archivado a su fecha.
- **Tamaño del árbol** (SEC-039): cada prueba de inclusión tiene que ser del tamaño `leaf_count` de la raíz firmada.

## 7. Operación

`make dev` levanta el contenedor `verifier`. En local también se puede lanzar con `uv run python -m argos_verifier.main` o usar solo la herramienta de línea de órdenes.

## 8. Verificación

- `services/verifier/tests/test_verifier.py`: un paquete íntegro pasa; un byte cambiado en el expediente, en el sobre o en un artefacto, una prueba de inclusión alterada, una raíz de otro árbol, una credencial revocada o de otro expediente fallan cada uno en su comprobación; un paquete mal formado no rompe; la línea de órdenes y la API dan el mismo informe; un paquete demasiado grande se rechaza.
- `services/verifier/tests/test_norms.py`: la IRI de una obligación abre su página (artículo, norma, texto oficial, retos y fecha); Turtle y JSON-LD con sus triples; la norma y el artículo también se abren; todo enlace de toda página de obligación lleva a una página que existe; lo que no está es `404`; el marcado del contenido se escapa; la portada lista todas las normas y obligaciones; cada página lleva el índice, las descargas y el aviso; y el catálogo se descarga en Markdown (una sección por obligación) y en PDF.
- `tests/architecture/test_verifier_isolation.py`: aislamiento de la plataforma.
- `tests/integration/test_verifier_bundle.py`: una campaña real exportada pasa todas las comprobaciones, sello incluido; un token real sobre otro objeto falla solo en `timestamp`; un artefacto alterado se señala por su posición.
- `tests/integration/test_verifier_container.py`: el contenedor da el mismo informe que la librería y no expone más que sus dos rutas.

## 9. Limitaciones conocidas y pendientes

- El paquete Python depende de `argos-evidence` entero para instalarse, aunque solo importe su núcleo puro. Distribuir el comprobador a terceros sin esas dependencias queda para la entrega del producto (Fase 10).
- El paquete de verificación lo exporta hoy una función; la descarga desde la consola llega con la Fase 08.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-18 | Comprobador público: librería, API, línea de órdenes y contenedor | F07-11 |
| 0.2.0-alpha | 2026-09-23 | Confianza por configuración (`Trust`, `ARGOS_VERIFIER_TRUST_FILE`, `--trust`), `dossier_authenticated`, lectura por partes con tope, límites de base58 y de la lista de estado, frescura de la revocación (`--at`) y tamaño del árbol contra la raíz firmada | F09-20 |
| 0.3.0-alpha | 2026-09-23 | Contenedor con la postura restringida de ARG-084 | F09-03 |
| 0.4.0-alpha | 2026-09-24 | Sin `/openapi.json` ni `/docs` (SEC-059) | F09-15 |
| 0.4.1-alpha | 2026-09-28 | Tipos inesperados en el bundle: comprobación fallida, no 500 | QA-29 (QA-052) |
| 0.5.0-alpha | 2026-10-08 | Catálogo normativo: `/norms/`, `/norms/{nombre}` (HTML, Turtle, JSON-LD) y descargas en Markdown y PDF; la imagen lleva `library/ontology` | petición directa (nota ARG-069) |
| 0.6.0-alpha | 2026-10-08 | `GET /verify` responde con una página (antes 405) para el QR del expediente; `/verify` publicado en el banco | petición directa (nota ARG-069) |
