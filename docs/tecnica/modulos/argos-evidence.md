---
id: MOD-argos-evidence
kind: module
title: Servicio de evidencia (argos-evidence)
module: argos-evidence
phases: ["07"]
version: 0.7.0-alpha
commit: pendiente
date: 2026-09-18
status: draft
confidentiality: client
---

# Servicio de evidencia (argos-evidence)

## 1. Propósito

Convierte el resultado de una campaña en evidencia que un tercero puede comprobar sin fiarse de ARGOS: artefactos inmutables, un árbol de Merkle que los encadena, la firma de su raíz, un sello de tiempo, el expediente y la credencial verificable. Implementa ARG-061 a ARG-070.

En su estado actual contiene el **árbol de Merkle por campaña (ARG-063)** con el anclaje de su raíz, el **cliente del almacén WORM (ARG-061)** , los **artefactos de evidencia (ARG-062)** , la **firma de la raíz de campaña (ARG-064)** , el **anclaje del diario (ARG-066)** , el **sellado temporal RFC 3161 con cola (ARG-065)** y el **expediente de campaña en JSON y PDF (ARG-067)**. El resto llega en las tareas siguientes de la Fase 07, y este documento está en estado `draft` hasta entonces.

## 2. Alcance y límites

- **Hace:** convertir cada veredicto en un artefacto canónico, minimizado y con su propio hash, escribirlo una vez, indexarlo y anunciarlo; escribir evidencia una sola vez en un almacén con bloqueo en modo conformidad y releerla; construir el árbol sobre el SHA-256 de los artefactos de una campaña, dar la prueba de inclusión de cada uno, verificarla y señalar qué artefactos ya no coinciden; anclar la raíz de cada campaña una sola vez.
- **Hará:** credencial (ARG-068) y publicación en espacios de datos (ARG-070).
- **No hace:** no decide conformidad (eso es del evaluador del motor de retos) ni modifica una raíz ya anclada.

## 3. Arquitectura

- `argos_evidence.merkle`: el árbol. **Solo biblioteca estándar**: el mismo fichero se entrega junto al expediente como verificador aislado (`python merkle.py <artefacto> <prueba.json>`).
- `argos_evidence.roots`: orden de las hojas y anclaje de la raíz en PostgreSQL.
- `argos_evidence.artifacts`: el artefacto de cada veredicto. JSON canónico con la misma función del diario (`argos_common.journal.canonicalize`), su propio SHA-256 calculado sin ese campo y la fecha en que se registró el veredicto, no la de escritura: el mismo veredicto da siempre los mismos bytes (nota ARG-062). Antes de escribir, rechaza cualquier valor que sea un DNI, NIE, NUSS o IBAN español validado, con los validadores de ARG-024.
- `argos_evidence.signing`: la firma de la raíz. El objeto firmado es JSON canónico y dice todo lo que la firma cubre: raíz de Merkle, número y orden de hojas, clave del árbol, **sello de campaña de la Fase 05**, cabeza del diario, momento, algoritmo (Ed25519) e identificador de la clave. Solo se firma una campaña sellada y con raíz; se firma una vez y el sobre (objeto, firma y clave pública) va al WORM.
- `argos_evidence.journal`: el diario anclado en la campaña (ARG-066). No hay un segundo verificador ni una segunda fórmula de hash: la cadena la comprueba `PostgresJournal.verify` (ADR-0002, nota ARG-066). Este módulo ancla la cabeza verificada del diario (`seq` y `entry_hash`) en el objeto firmado de la campaña: después, aunque alguien reescriba toda la historia y recalcule todos los hashes, el asiento anclado ya no tiene el hash anclado. También escribe en el WORM el informe de verificación del diario de cada campaña.
- `argos_evidence.tsa`: sellado temporal RFC 3161. La firma prueba quién; el sello prueba cuándo, y lo dice una autoridad ajena. El appliance puede estar aislado (P-02), así que el sellado es asíncrono: el sobre firmado entra en la cola al firmarse y se ve «en cola» hasta que exista un token verificado. Hay dos caminos al token, en línea (`process_queue`) y aislado (`export_requests` / `import_replies`), y **un solo verificador** (`verify_reply`, sobre `rfc3161-client`, Apache-2.0): estado, cadena hasta una raíz de confianza, nonce de la última petición, certificado de sellado y SHA-256 de los bytes exactos guardados en el WORM. El token se guarda en el WORM junto al objeto (`<clave>.tsr`).
- `argos_evidence.dossier`: el expediente, lo que el DPO entrega a un auditor o a un inspector (nota ARG-067). `build` lo ensambla en JSON canónico a partir de registros que ya existen (campaña y sello, resultados por resultado y por obligación, aprobaciones, hallazgos, textos redactados con su marca y cadena de evidencia completa), sin ningún momento de ensamblado dentro: el mismo estado da siempre el mismo hash. `render` genera el PDF **solo desde ese JSON**, tras comprobar su hash, con **ReportLab** (BSD) en modo invariante: el mismo expediente da el mismo PDF byte a byte. Cada página lleva el SHA-256 del JSON y la portada un QR con la URL del comprobador público y ese hash. Todo texto redactado por el modelo sale bajo la marca «Texto asistido por IA».
- `argos_evidence.worm`: cliente del almacén WORM (VersityGW con *object lock*, ADR-0010). Solo escribe una vez, lee y consulta la retención; **no tiene ninguna primitiva de borrado**.

Reglas del árbol:

- Las hojas y los nodos internos se calculan con prefijos de dominio distintos: `SHA-256(0x00 ‖ sha256 del artefacto)` y `SHA-256(0x01 ‖ izquierdo ‖ derecho)`. Así se evitan las segundas preimágenes entre niveles.
- En un nivel impar, el último nodo sube **sin duplicarse**. Duplicarlo daría la misma raíz a dos listas de artefactos distintas; los vectores de prueba incluyen el contraejemplo.
- Las hojas se ordenan por `verdict_id` ascendente, en su forma textual canónica. Con ese orden cualquiera reconstruye el mismo árbol a partir de los artefactos.
- La prueba de inclusión se verifica con la posición **y el tamaño** del árbol: de ellos se deduce en qué niveles subió la hoja sin hermano. Una prueba presentada para otra posición o para otro tamaño no verifica.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Función pública | `merkle.build_tree(hashes) -> MerkleTree` | Árbol inmutable con todos sus niveles; `root` y `size`. Error si no hay artefactos o si alguno no es un SHA-256 |
| Función pública | `merkle.proof(tree, index)` | Prueba de inclusión: lista de `("L" \| "R", hash del hermano)` desde la hoja |
| Función pública | `merkle.verify_proof(sha256, index, size, path, root) -> bool` | Comprueba un artefacto sin el árbol |
| Función pública | `merkle.failing_leaves(hashes, tree) -> list[int]` | Posiciones cuyo artefacto ya no coincide; error si falta o sobra alguno |
| Función pública | `roots.tree_for({verdict_id: sha256})`, `roots.record_root(...)`, `roots.get_root(...)` | Árbol en el orden documentado y anclaje de la raíz |
| Función pública | `worm.WormStore.put_immutable(key, data, retain_until) -> StoredObject` | Escritura condicional (`If-None-Match: *`) con retención en modo conformidad y suma SHA-256; relee la versión y comprueba el hash. `WormAlreadyStoredError` si la clave ya existe |
| Función pública | `worm.WormStore.get(key, version_id=None)`, `worm.WormStore.retention(key, version_id)` | Lectura por versión y consulta de la retención |
| Función pública | `worm.ensure_buckets(client, default_retention_days)` | Crea, de forma idempotente, `evidence` (bloqueo en conformidad con retención por defecto) y `working` (versionado, sin bloqueo) |
| Función pública | `artifacts.write_artifact(dsn, store, campaign_id, verdict_id, retain_until) -> ArtifactRecord` | Escribe el artefacto de un veredicto en `campaigns/{campaign_id}/artifacts/{verdict_id}.json` y lo indexa. Idempotente: un reintento comprueba byte a byte lo ya guardado |
| Función pública | `artifacts.build_artifact(row)`, `artifacts.verify_artifact(bytes)`, `artifacts.personal_identifiers(document)` | Construcción, verificación aislada del hash interno y búsqueda de identificadores personales |
| Evento publicado | `argos.evidence.artifact_written` (`evidence.artifact_written.v1`, stream `EVIDENCE`) | `campaign_id`, `verdict_id`, `key`, `version_id` y `sha256` del artefacto; con `announce_artifact(bus, record)` |
| Tabla o migración | `argos.evidence_index` (`0022_evidence_index.sql`) | Clave, versión y SHA-256 del fichero de cada artefacto; se escribe una vez |
| Función pública | `worm.WormStore.version_of(key)` | Versión actual de una clave, para que un reintento encuentre lo que guardó el primero |
| Función pública | `signing.sign_campaign_root(dsn, store, signer, campaign_id, journal_head, retain_until) -> SignatureRecord` | Firma la raíz de una campaña sellada, guarda el sobre en `campaigns/{campaign_id}/root-signature.json`, lo registra y lo anota en el diario (`campaign.root_signed`). Idempotente |
| Función pública | `journal.anchor_head(dsn) -> {seq, entry_hash}` | Cabeza actual del diario tras verificar toda la cadena; si la cadena está rota no se ancla (`JournalAnchorError`) |
| Función pública | `journal.verify_anchor(dsn, head) -> AnchorCheck` | Comprueba la cadena hasta la cabeza anclada y que el asiento anclado conserva su hash; `intact`, `head_matches` y anomalías |
| Función pública | `journal.journal_report(dsn, store, campaign_id, head, retain_until) -> ReportRecord` | Informe de verificación del diario en `campaigns/{campaign_id}/journal-report.json`, con su propio hash; sin fecha dentro, así que un reintento lo comprueba byte a byte |
| Función pública | `artifacts.seal_document(document)`, `artifacts.file_digest(body)` | Añadir a un documento su propio SHA-256 autoexcluido y calcular el hash de un fichero guardado; los usan artefactos e informe |
| Función pública | `tsa.process_queue(dsn, store, transport, roots, retain_until) -> QueueSummary` | Intenta sellar cada objeto en cola; un fallo se anota (intentos y último error) y el objeto sigue en cola |
| Función pública | `tsa.export_requests(dsn, store)`, `tsa.import_replies(dsn, store, replies, roots, retain_until)` | Modo aislado: consultas para sellar fuera y aceptación de las respuestas traídas de vuelta |
| Función pública | `tsa.accept_reply(...)`, `tsa.verify_reply(reply, data, nonce, roots)`, `tsa.stamp_of(dsn, key)`, `tsa.enqueue(...)`, `tsa.http_transport(url)` | Verificador único, estado visible de cada objeto y transporte HTTP (`application/timestamp-query`) |
| Tabla o migración | `argos.tsa_queue` (`0024_tsa_queue.sql`) | Objeto, versión y hash; estado `queued`/`stamped`, intentos, último error, nonce, token, `gen_time` y política. Una entrada sellada es definitiva y ninguna se borra |
| Servicio del entorno | `tsa` (`127.0.0.1:3180`, red `evidence`, volumen `tsa-data`) | TSA de desarrollo: `openssl ts` con una autoridad de pruebas creada al primer arranque; política `1.2.3.4.1`, **no cualificada**. `GET /ca.pem` da su raíz |
| Función pública | `dossier.assemble(dsn, store, campaign_id, verifier_url) -> bytes` | JSON canónico del expediente de una campaña sellada, con su propio SHA-256 |
| Función pública | `dossier.render_pdf(dossier_json, verifier_url) -> bytes`, `dossier.qr_payload(url, sha256)` | PDF reproducible desde el JSON; rechaza un JSON cuyo hash no cuadra (`DossierError`) |
| Función pública | `dossier.write_dossier(dsn, store, campaign_id, verifier_url, retain_until) -> DossierRecord` | Guarda JSON y PDF en `campaigns/{campaign_id}/dossier/{sha256}.json|.pdf` y los registra; el mismo estado da el mismo registro, uno nuevo (p. ej. con el sello) da otro y se conservan todos |
| Tabla o migración | `argos.dossiers` (`0025_dossiers.sql`) | Un expediente por hash con sus claves y versiones en el WORM; escritura única |
| Función pública | `signing.signing_payload(...)`, `signing.sign_payload(signer, payload)`, `signing.verify_envelope(bytes, public_key) -> bool`, `signing.key_id(public_key)` | Objeto de firma, sobre y verificación con la clave pública, sin la plataforma |
| Tabla o migración | `argos.campaign_signatures` (`0023_campaign_signatures.sql`) | Clave y versión del sobre, SHA-256, identificador de la clave y marca `non_production`; se escribe una vez |
| Servicio del entorno | `evidence-store` (`127.0.0.1:7075`, red `evidence`, volumen `evidence-data`) | VersityGW v1.8.0, backend POSIX con versiones |
| Tabla o migración | `argos.campaign_roots` (`0021_campaign_roots.sql`) | Raíz, número de hojas, orden y clave del árbol en el WORM; se escribe una vez |
| Herramienta de línea de órdenes | `python merkle.py <artefacto> <prueba.json>` | Verificador aislado; código de salida 0 si el artefacto pertenece al árbol |

## 5. Configuración

Usa la cadena de conexión a PostgreSQL de la plataforma (`ARGOS_DATABASE_URL`, desde `argos-common`). La firma usa cualquier `Signer` de `argos_common.release`: en desarrollo, `VaultTransitSigner` con la clave `argos-evidence` del motor Transit (Ed25519, no exportable; la crea `deploy/dev/vault/setup.sh`); en el appliance, `TpmSigner` (F07-15). El cliente WORM recibe un cliente S3 ya construido; la configuración del servicio (punto de acceso, credenciales y retención por defecto, 10 años en producción y 1 día en desarrollo) llega con F07-13. En desarrollo las credenciales del almacén son triviales a propósito y solo escuchan en `127.0.0.1`.

## 6. Seguridad y tratamiento de datos

- **Minimización (P-16):** el artefacto solo lleva lo que la sonda dejó pasar en el veredicto. Si aun así contuviera un DNI, NIE, NUSS o IBAN validado, no se escribe (`ArtifactNotMinimisedError`) y el error señala la ruta JSON.
- El árbol y la raíz solo manejan **hashes** de artefactos, nunca su contenido.
- `argos.evidence_index` y `argos.campaign_signatures` son de escritura única, como `argos.campaign_roots`.
- **Custodia de la clave:** la clave privada de firma nunca está en disco ni en memoria de ARGOS; firma el custodio (Vault Transit en desarrollo, TPM en el appliance).
- **Sellado temporal:** ningún token se acepta sin pasar por el verificador único; un token de otro objeto, de otra petición (nonce) o de una autoridad sin raíz de confianza se rechaza y el objeto sigue en cola. Los sellos de la TSA de desarrollo llevan una política de pruebas y no son cualificados (nota ARG-064-065); la TSA cualificada llega con F07-16.
- **Expediente:** solo lleva lo que ya está en los registros minimizados (veredictos, hallazgos sin datos del cliente, textos verificados por el redactor de la Fase 06). La firma de desarrollo y el sello en cola se muestran como tales en el PDF.
- **Licencias:** el PDF no usa PyMuPDF (AGPL), que solo emplea la herramienta interna `docs_pack` y los tests como lector; el servicio usa ReportLab (BSD).
- **Diario anclado:** `sign_campaign_root` ancla por defecto la cabeza verificada del diario, y un diario roto no se ancla.
- **Nada firmado en desarrollo pasa por producción:** un firmante que no se declara `production` marca cada objeto con `non_production: true` dentro de lo firmado; la marca queda también en `argos.campaign_signatures` y en el diario. Solo el `TpmSigner` del appliance se declarará de producción (nota ARG-064-065).
- `argos.campaign_roots` es de escritura única: un disparador rechaza `UPDATE`, `DELETE` y `TRUNCATE`.
- La inmutabilidad de la evidencia es **técnica**: la da el almacén con bloqueo en modo conformidad, que rechaza borrar, acortar la retención o relajar el modo, también a su cuenta raíz. Lo demuestra la prueba de conformidad.
- La garantía cubre el acceso por la API S3; el acceso de superusuario al sistema de ficheros del appliance lo cierran el cifrado y el endurecimiento del appliance (ADR-0010).
- Decisiones aplicables: ADR-0010 (almacén WORM), ADR-0011 (credencial) y notas ARG-062, ARG-064-065 y ARG-067.

## 7. Operación

Por ahora es una librería. El almacén `evidence-store` arranca con `make dev`; los buckets los crea `ensure_buckets`. Borrar lo escrito en desarrollo no es posible por la API: se resetea quitando el volumen `evidence-data`. El servicio y su contenedor llegan con F07-13.

## 8. Verificación

- `tests/unit/test_merkle_vectors.py`: vectores calculados con un script independiente (`tools/merkle_vectors.py`), sin compartir código con el árbol.
- `services/evidence/tests/test_merkle_pure.py`: vectores exactos; inclusión en árboles de 1 a 64 hojas; 2000 corrupciones de un byte con semilla fija, todas detectadas y localizadas.
- `services/evidence/tests/test_merkle_standalone_pure.py`: solo biblioteca estándar y verificador por línea de órdenes.
- `tests/integration/test_campaign_roots.py`: orden de las hojas y escritura única de la raíz.
- `services/evidence/tests/test_artifacts_pure.py`: mismos bytes para el mismo veredicto, forma canónica del diario, hash interno que detecta cualquier cambio, identificadores personales rechazados y evento en el stream `EVIDENCE`.
- `tests/integration/test_artifacts.py`: un veredicto real escrito en el WORM e indexado; reintento idempotente; índice perdido reconstruido desde los mismos bytes; índice de escritura única.
- `services/evidence/tests/test_signing_pure.py`: objeto estable, verificación con la clave pública, cualquier campo alterado rompe la firma, otra clave no verifica y la marca `non_production`.
- `tests/integration/test_signing.py`: firma con la clave de Vault de una campaña sellada, sobre en el WORM, anotación en el diario, idempotencia, rechazo de campañas sin sellar o sin raíz y tabla de escritura única.
- `tests/integration/test_journal_anchor.py`: cabeza anclada tras verificar; diario roto que no se ancla; asiento anterior alterado detectado; reescritura completa de la historia con hashes recalculados detectada por el anclaje; firma que ancla la cabeza por defecto; informe verificable e idempotente en el WORM; y ninguna segunda fórmula de hash del diario.
- `services/evidence/tests/test_tsa_pure.py` y `tests/integration/test_tsa.py`: la firma encola el sello y el estado se ve; sello verificado y guardado en el WORM; un fallo deja el objeto en cola y el reintento lo sella; un token de otro objeto se rechaza; exportación e importación aisladas; una respuesta a una petición anterior se rechaza por el nonce; una entrada sellada no cambia ni desaparece.
- `services/evidence/tests/test_dossier_pure.py` y `tests/integration/test_dossier.py`: PDF idéntico para el mismo expediente; hash en cada página; QR con la URL y el hash; cada texto asistido con su marca y ninguna marca sin texto; cifras del JSON; JSON alterado rechazado; firma de desarrollo y sello en cola visibles; expediente ensamblado desde una campaña real; mismo estado, mismo expediente; campaña sin sellar rechazada; JSON y PDF en el WORM y nueva versión cuando llega el sello.
- `tests/integration/test_worm_conformance.py`: la prueba de conformidad de ADR-0010 contra el almacén real (borrar, sobrescribir y acortar la retención fallan).
- `tests/architecture/test_worm_has_no_delete.py`: el cliente no expone ni alcanza ninguna primitiva de borrado, ni por nombre ni por acceso dinámico.

## 9. Limitaciones conocidas y pendientes

- El árbol completo se guardará en el WORM al cerrar la campaña (F07-13); hasta entonces `tree_key` es solo la clave prevista.
- La expiración a un año del bucket `working` que prevé ADR-0010 no está configurada: el cliente no toca reglas de ciclo de vida, y se decidirá con la operación del almacén (Fase 10).

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-18 | Árbol de Merkle con separación de dominio, verificador aislado y anclaje de la raíz | F07-03 |
| 0.2.0-alpha | 2026-09-18 | Cliente del almacén WORM sin primitiva de borrado y almacén `evidence-store` en el entorno | F07-04 |
| 0.3.0-alpha | 2026-09-18 | Artefactos de evidencia canónicos, minimizados, indexados y anunciados | F07-05 |
| 0.4.0-alpha | 2026-09-18 | Firma de la raíz de campaña con clave no exportable y marca de no producción | F07-06 |
| 0.5.0-alpha | 2026-09-18 | Cabeza del diario anclada en la firma e informe de verificación del diario en el WORM | F07-07 |
| 0.6.0-alpha | 2026-09-18 | Sellado temporal RFC 3161 con cola, modo aislado y TSA de desarrollo | F07-08 |
| 0.7.0-alpha | 2026-09-18 | Expediente de campaña en JSON canónico y PDF reproducible con QR | F07-09 |
