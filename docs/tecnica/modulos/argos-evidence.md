---
id: MOD-argos-evidence
kind: module
title: Servicio de evidencia (argos-evidence)
module: argos-evidence
phases: ["07"]
version: 0.17.0-alpha
commit: 8dcef99
date: 2026-09-23
status: current
confidentiality: client
---

# Servicio de evidencia (argos-evidence)

## 1. Propósito

Convierte el resultado de una campaña en evidencia que un tercero puede comprobar sin fiarse de ARGOS: artefactos inmutables, un árbol de Merkle que los encadena, la firma de su raíz, un sello de tiempo, el expediente y la credencial verificable. Implementa ARG-061 a ARG-070.

En su estado actual contiene el **árbol de Merkle por campaña (ARG-063)** con el anclaje de su raíz, el **cliente del almacén WORM (ARG-061)** , los **artefactos de evidencia (ARG-062)** , la **firma de la raíz de campaña (ARG-064)** , el **anclaje del diario (ARG-066)** , el **sellado temporal RFC 3161 con cola (ARG-065)** , el **expediente de campaña en JSON y PDF (ARG-067)** , la **credencial verificable (ARG-068)** , su **publicación en espacios de datos vía EDC (ARG-070)** y el **cierre de campaña encadenado** con sus contenedores (F07-13). Con esto el módulo está completo para la Fase 07; el documento sale de `draft`. El resto llega en las tareas siguientes de la Fase 07, y este documento está en estado `draft` hasta entonces.

## 2. Alcance y límites

- **Hace:** convertir cada veredicto en un artefacto canónico, minimizado y con su propio hash, escribirlo una vez, indexarlo y anunciarlo; escribir evidencia una sola vez en un almacén con bloqueo en modo conformidad y releerla; construir el árbol sobre el SHA-256 de los artefactos de una campaña, dar la prueba de inclusión de cada uno, verificarla y señalar qué artefactos ya no coinciden; anclar la raíz de cada campaña una sola vez.
- **No hace:** no decide conformidad (eso es del evaluador del motor de retos) ni modifica una raíz ya anclada.

## 3. Arquitectura

- `argos_evidence.merkle`: el árbol. **Solo biblioteca estándar**: el mismo fichero se entrega junto al expediente como verificador aislado (`python merkle.py <artefacto> <prueba.json>`).
- `argos_evidence.roots`: orden de las hojas y anclaje de la raíz en PostgreSQL.
- `argos_evidence.artifacts`: el artefacto de cada veredicto. JSON canónico con la misma función del diario (`argos_common.journal.canonicalize`), su propio SHA-256 calculado sin ese campo y la fecha en que se registró el veredicto, no la de escritura: el mismo veredicto da siempre los mismos bytes (nota ARG-062). Antes de escribir, rechaza cualquier valor que sea un DNI, NIE, NUSS o IBAN español validado, con los validadores de ARG-024.
- `argos_evidence.signing`: la firma de la raíz. El objeto firmado es JSON canónico y dice todo lo que la firma cubre: raíz de Merkle, número y orden de hojas, clave del árbol, **sello de campaña de la Fase 05**, cabeza del diario, momento, algoritmo (Ed25519) e identificador de la clave. Solo se firma una campaña sellada y con raíz; se firma una vez y el sobre (objeto, firma y clave pública) va al WORM.
- `argos_evidence.journal`: el diario anclado en la campaña (ARG-066). No hay un segundo verificador ni una segunda fórmula de hash: la cadena la comprueba `PostgresJournal.verify` (ADR-0002, nota ARG-066). Este módulo ancla la cabeza verificada del diario (`seq` y `entry_hash`) en el objeto firmado de la campaña: después, aunque alguien reescriba toda la historia y recalcule todos los hashes, el asiento anclado ya no tiene el hash anclado. También escribe en el WORM el informe de verificación del diario de cada campaña.
- `argos_evidence.tsa`: sellado temporal RFC 3161. La firma prueba quién; el sello prueba cuándo, y lo dice una autoridad ajena. El appliance puede estar aislado (P-02), así que el sellado es asíncrono: el sobre firmado entra en la cola al firmarse y se ve «en cola» hasta que exista un token verificado. Hay dos caminos al token, en línea (`process_queue`) y aislado (`export_requests` / `import_replies`), y **un solo verificador** (`verify_reply`, sobre `rfc3161-client`, Apache-2.0): estado, cadena hasta una raíz de confianza, nonce de la última petición, certificado de sellado y SHA-256 de los bytes exactos guardados en el WORM. El token se guarda en el WORM junto al objeto (`<clave>.tsr`).
- `argos_evidence.dossier`: el expediente, lo que el DPO entrega a un auditor o a un inspector (nota ARG-067). `build` lo ensambla en JSON canónico a partir de registros que ya existen (campaña y sello, resultados por resultado y por obligación, aprobaciones, hallazgos, textos redactados con su marca y cadena de evidencia completa), sin ningún momento de ensamblado dentro: el mismo estado da siempre el mismo hash. `render` genera el PDF **solo desde ese JSON**, tras comprobar su hash, con **ReportLab** (BSD) en modo invariante: el mismo expediente da el mismo PDF byte a byte. Cada página lleva el SHA-256 del JSON y la portada un QR con la URL del comprobador público y ese hash. Todo texto redactado por el modelo sale bajo la marca «Texto asistido por IA».
- `argos_evidence.credential`: la credencial verificable de cada expediente (ADR-0011). W3C VC 2.0 con prueba `DataIntegrityProof` y suite **`eddsa-jcs-2022`**: forma canónica JCS del RFC 8785 (paquete `rfc8785`, no la canonicalización del diario) y firma Ed25519 sobre `SHA-256(opciones) ‖ SHA-256(documento)`; pasa los vectores publicados por el W3C byte a byte. Emisor `did:web` con una clave Multikey para aserciones, que es la misma que firma las raíces. El sujeto se construye campo a campo (campaña, hash del expediente, raíz, versiones, resultados, hallazgos por severidad y marca `nonProduction`): **sin datos personales ni nombres de sistemas**. La revocación es un bit en una **Bitstring Status List** (131 072 bits, GZIP y base64url), reconstruida desde las revocaciones registradas y firmada otra vez: la credencial no se toca.
- `argos_evidence.core`: el **núcleo puro de verificación** (`integrity`: forma canónica y hash autoexcluido; `envelope`: sobre firmado de la raíz; `timestamp`: verificador único de sellos RFC 3161, con nonce opcional para quien no hizo la petición). Junto con `merkle` y los módulos puros de `credential` (`proof`, `did`, `multibase`, `status`, `verify`), es lo único que usa el comprobador público: sin base de datos, sin almacén y sin red. El resto del paquete lo reutiliza en vez de duplicarlo.
- `argos_evidence.workflow`: `EvidenceWorkflow`, cola `argos-evidence`. Lleva una campaña sellada de sus veredictos a su credencial: artefactos, árbol de Merkle en el WORM y raíz, firma con la cabeza del diario anclada, sello de tiempo, expediente y credencial. Cada paso es una actividad idempotente (`argos_evidence.activities`): un reintento tras un fallo a mitad deja exactamente los mismos objetos en el WORM. Si el sello no llega, el expediente lo dice («sello en cola») y recibe su credencial. Cuando el sello llega, se hace un expediente nuevo con su credencial y la anterior se revoca por sustituida; el expediente anterior se conserva.
- `argos_evidence.worker`: el worker de Temporal. Escucha `argos.campaign.sealed` (consumidor duradero `evidence-on-seal`) y arranca un workflow por campaña con id `evidence-{campaign_id}`, así que un anuncio repetido no arranca nada dos veces. Ignora los anuncios de campañas que su base no tiene selladas. El motor de retos no llama a este servicio: solo anuncia.
- `argos_evidence.api`: lo que el servicio publica para que cualquiera verifique. Documento DID en `/.well-known/did.json`, listas de estado firmadas en `/status/{n}` y credenciales en `/credentials/{uuid}` (`application/vc+json`, el destino del activo EDC). No sirve expedientes ni artefactos, que son del cliente.
- `argos_evidence.settings`, `argos_evidence.service`: configuración `ARGOS_EVIDENCE_*` y montaje de las piezas.
- `argos_evidence.dataspace.edc`: publica la **credencial, y solo la credencial,** como activo de un conector Eclipse Dataspace Connector a través de su Management API v3: activo, definición de política y definición de contrato. La política sale de una biblioteca cerrada (`use_only`, `no_redistribution`, `retention`) y se comprueba antes de enviar con el mismo lector ODRL que lee las políticas recibidas (ARG-035, `argos_ontology.odrl.parse_policy`): si tiene una cláusula que ARGOS no sabría verificar, no se envía. Por eso la «atribución» del documento de fase no está en la biblioteca. Un expediente, o cualquier documento que no sea una credencial de campaña firmada, se rechaza antes de tocar la red.
- `argos_evidence.bundle`: el **paquete de verificación** de un expediente para un tercero (`export_bundle`): expediente, sobre firmado, token de sello y cada artefacto con su prueba de inclusión, en bytes exactos, junto a la credencial, el documento DID, la lista de estado y las raíces de la TSA.
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
| Función pública | `credential.issue.issue_credential(dsn, store, signer, issuer, status_base_url, dossier_sha256, retain_until, issued_by="system:evidence") -> CredentialRecord` | Emite una vez por expediente y guarda la credencial en `campaigns/{campaign_id}/credential/{id}.json`; diario `credential.issued` |
| Función pública | `credential.issue.revoke_credential(dsn, credential_id, reason, revoked_by)`, `status_list_credential(...)` | Revocación con motivo (diario `credential.revoked`) y lista de estado firmada reconstruida |
| Función pública | `credential.issue.verify_credential(credential, did_document, status_list) -> CredentialCheck` | Prueba contra el DID, método de verificación del emisor y bit de revocación; motivos explícitos (`proof`, `revoked`, `status not checked`…) |
| Función pública | `credential.proof.add_proof`, `verify_proof`, `hash_data`, `jcs`; `credential.did.did_web`, `did_web_url`, `did_document`; `credential.status.encode_list`, `decode_list` | Suite `eddsa-jcs-2022`, `did:web` y lista de estado |
| Tabla o migración | `argos.credentials`, `argos.credential_revocations`, secuencia `argos.credential_status_seq` (`0026_credentials.sql`) | Una credencial por expediente con su lista e índice; revocaciones con motivo; escritura única |
| Workflow | `workflow.EvidenceWorkflow.run(campaign_id, stamp_attempts, stamp_wait_seconds)` (cola `argos-evidence`) | Actividades `evidence_write_artifacts`, `evidence_build_root`, `evidence_sign_root`, `evidence_stamp`, `evidence_write_dossier`, `evidence_issue_credential`; devuelve artefactos, expediente final y estado del sello |
| Evento consumido | `argos.campaign.sealed` (`challenge.campaign_sealed.v1`) | Arranca el workflow de la campaña si su base la tiene sellada |
| API | `GET /.well-known/did.json`, `GET /status/{n}`, `GET /credentials/{uuid}`, `GET /health` (puerto 8008) | Material público de verificación; sin documentación interactiva |
| Objeto WORM | `campaigns/{campaign_id}/merkle-tree.json` | El árbol completo (hojas en orden de `verdict_id`, niveles y raíz) con su propio hash |
| Servicio del entorno | `evidence-worker`, `evidence-api` (`127.0.0.1:8008`), redes `default` y `evidence` | Una imagen, `argos-evidence`, con dos procesos |
| Función pública | `dataspace.edc.EdcClient(management_url, api_key).publish_credential(credential, credential_url, choice) -> PublishRecord` | Activo, política y contrato; un 409 del conector cuenta como ya publicado |
| Función pública | `dataspace.edc.build_policy(asset_id, choice)`, `record_publication(dsn, credential_id, record, by)` | Política ODRL de la biblioteca y registro único con anotación `credential.published` en el diario |
| Tabla o migración | `argos.dataspace_publications` (`0027_dataspace_publications.sql`) | Qué credencial salió, como qué activo, bajo qué política y quién lo decidió; escritura única |
| Servicio del entorno | `edc-mock` (`127.0.0.1:19193`, red `evidence`) | Management API v3 simulada: valida los cuerpos, exige la clave y guarda en memoria. El conector real, Gaia-X y Pontus-X llegan con F07-16 |
| Función pública | `bundle.export_bundle(dsn, store, dossier_sha256, *, did_document, status_list, tsa_roots_pem) -> dict` | Paquete `argos/verification-bundle/1` que comprueba `argos-verifier` |
| Función pública | `core.integrity.*`, `core.envelope.*`, `core.timestamp.verify_reply`, `credential.verify.verify_credential` | Núcleo puro de verificación (antes en `artifacts`, `signing`, `tsa` y `credential.issue`, que ahora lo importan) |
| Función pública | `signing.signing_payload(...)`, `signing.sign_payload(signer, payload)`, `signing.verify_envelope(bytes, public_key) -> bool`, `signing.key_id(public_key)` | Objeto de firma, sobre y verificación con la clave pública, sin la plataforma |
| Tabla o migración | `argos.campaign_signatures` (`0023_campaign_signatures.sql`) | Clave y versión del sobre, SHA-256, identificador de la clave y marca `non_production`; se escribe una vez |
| Servicio del entorno | `evidence-store` (`127.0.0.1:7075`, red `evidence`, volumen `evidence-data`) | VersityGW v1.8.0, backend POSIX con versiones |
| Tabla o migración | `argos.campaign_roots` (`0021_campaign_roots.sql`) | Raíz, número de hojas, orden y clave del árbol en el WORM; se escribe una vez |
| Herramienta de línea de órdenes | `python merkle.py <artefacto> <prueba.json>` | Verificador aislado; código de salida 0 si el artefacto pertenece al árbol |

## 5. Configuración

Usa de `argos-common` la base (`ARGOS_DATABASE_URL`), Temporal, NATS y Vault. La contraseña de la base llega en un fichero, `ARGOS_DATABASE_PASSWORD_FILE` (en desarrollo, `/run/secrets/db-evidence`, que genera `tools/dev_db_users.py`), y no en la cadena de conexión. Lo propio va en `ARGOS_EVIDENCE_*` (`EvidenceSettings`): `ISSUER_DID`, `STATUS_BASE_URL`, `CREDENTIAL_BASE_URL`, `VERIFIER_URL`, `RETENTION_DAYS` (10 años por defecto; 1 día en desarrollo), `S3_ENDPOINT`/`S3_ACCESS_KEY`/`S3_SECRET_KEY` (secreto), `SIGNING_KEY` (clave de Transit), `TSA_URL`, `TSA_ROOTS_FILE` (en desarrollo, `TSA_ROOTS_URL` toma la raíz de la TSA de pruebas), `STAMP_ATTEMPTS` y `STAMP_WAIT_SECONDS`. La firma usa cualquier `Signer` de `argos_common.release`: en desarrollo, `VaultTransitSigner` con la clave `argos-evidence` del motor Transit (Ed25519, no exportable; la crea `deploy/dev/vault/setup.sh`); en el appliance, `TpmSigner` (F07-15). El cliente WORM recibe un cliente S3 ya construido; la configuración del servicio (punto de acceso, credenciales y retención por defecto, 10 años en producción y 1 día en desarrollo) llega con F07-13. En desarrollo las credenciales del almacén son triviales a propósito y solo escuchan en `127.0.0.1`.

## 6. Seguridad y tratamiento de datos

- **Postura del contenedor** (F09-03, ARG-084, P-22): corre como `10001:10001`, sin capacidades (`cap_drop: [ALL]`), con la raíz de solo lectura y `/tmp` en `tmpfs`, sin escalada (`no-new-privileges`) y con el perfil seccomp propio `platform/k8s/security/seccomp/evidence.json` (deniega por defecto y no permite nada que abra el host; `ioctl` queda por el TPM del appliance). La imagen no lleva `bash`. En el compose lo exige `tests/security/test_compose_posture.py`, y `tests/integration/test_container_posture.py` lo comprueba dentro del contenedor en marcha.
- **Base de datos con mínimo privilegio** (F09-04, ARG-085): el servicio se conecta como `login_evidence`, miembro del rol `svc_evidence` (migración `0033`), y nunca como superusuario. El rol tiene solo las tablas y operaciones que usa su código; el diario se escribe únicamente con `argos.journal_append()`. Lo comprueban `tests/integration/test_service_roles.py` (la matriz `tests/fixtures/db_access_matrix.yaml` y el usuario de cada contenedor en marcha).
- **Minimización (P-16):** el artefacto solo lleva lo que la sonda dejó pasar en el veredicto. Si aun así contuviera un DNI, NIE, NUSS o IBAN validado, no se escribe (`ArtifactNotMinimisedError`) y el error señala la ruta JSON.
- El árbol y la raíz solo manejan **hashes** de artefactos, nunca su contenido.
- `argos.evidence_index` y `argos.campaign_signatures` son de escritura única, como `argos.campaign_roots`.
- **Custodia de la clave:** la clave privada de firma nunca está en disco ni en memoria de ARGOS; firma el custodio (Vault Transit en desarrollo, TPM en el appliance).
- **Sellado temporal:** ningún token se acepta sin pasar por el verificador único; un token de otro objeto, de otra petición (nonce) o de una autoridad sin raíz de confianza se rechaza y el objeto sigue en cola. Los sellos de la TSA de desarrollo llevan una política de pruebas y no son cualificados (nota ARG-064-065); la TSA cualificada llega con F07-16.
- **Expediente:** solo lleva lo que ya está en los registros minimizados (veredictos, hallazgos sin datos del cliente, textos verificados por el redactor de la Fase 06). La firma de desarrollo y el sello en cola se muestran como tales en el PDF.
- **Licencias:** el PDF no usa PyMuPDF (AGPL), que solo emplea la herramienta interna `docs_pack` y los tests como lector; el servicio usa ReportLab (BSD).
- **Credencial sin datos personales:** el sujeto solo admite la lista cerrada `SUBJECT_KEYS` y pasa por los validadores de identificadores; un test lo vigila. Las credenciales firmadas con la clave de desarrollo llevan `nonProduction: true`.
- **Espacios de datos:** publicar es opcional y lo decide el cliente por campaña; lo que sale es la credencial, que no lleva datos personales y cita el expediente por su hash. La clave de la Management API es un secreto del servicio (en el appliance, en Vault); en desarrollo es trivial y solo escucha en `127.0.0.1`.
- **Diario anclado:** `sign_campaign_root` ancla por defecto la cabeza verificada del diario, y un diario roto no se ancla.
- **Nada firmado en desarrollo pasa por producción:** un firmante que no se declara `production` marca cada objeto con `non_production: true` dentro de lo firmado; la marca queda también en `argos.campaign_signatures` y en el diario. Solo el `TpmSigner` del appliance se declarará de producción (nota ARG-064-065).
- `argos.campaign_roots` es de escritura única: un disparador rechaza `UPDATE`, `DELETE` y `TRUNCATE`.
- La inmutabilidad de la evidencia es **técnica**: la da el almacén con bloqueo en modo conformidad, que rechaza borrar, acortar la retención o relajar el modo, también a su cuenta raíz. Lo demuestra la prueba de conformidad.
- La garantía cubre el acceso por la API S3; el acceso de superusuario al sistema de ficheros del appliance lo cierran el cifrado y el endurecimiento del appliance (ADR-0010).
- Decisiones aplicables: ADR-0010 (almacén WORM), ADR-0011 (credencial) y notas ARG-062, ARG-064-065 y ARG-067.
- **Lista de estado con caducidad y sin firmar en cada petición** (SEC-018, SEC-056, F09-20): se emite con `validUntil` a 24 h (`STATUS_LIST_TTL`); `EvidenceActivities.status_list` la guarda firmada y solo la vuelve a firmar si cambian las revocaciones o ha pasado la mitad de su vida; `GET /status/{n}` da 404 para una lista sin credenciales.
- **`did_web_url`** solo acepta un host (y puerto) y rutas sin `@`, `/`, `?` ni `#` una vez decodificados (SEC-038).
- **Anclajes del emisor:** `EvidenceActivities.trust_anchors()` devuelve lo que un tercero necesita para confiar (huella de la clave y raíces de TSA); se entrega por un canal propio, nunca dentro del bundle.

## 7. Operación

`make dev` levanta `evidence-worker` y `evidence-api` junto al almacén, la TSA y el EDC simulado; los buckets los crea el propio servicio al arrancar (`ensure_buckets`). Cada campaña que el motor sella llega sola a su credencial. Borrar lo escrito en desarrollo no es posible por la API: se resetea quitando el volumen `evidence-data`. 

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
- `services/evidence/tests/test_credential_vectors.py`: vectores del W3C de `eddsa-jcs-2022` (claves, JCS, hashes, firma, `proofValue` y documento firmado) byte a byte.
- `services/evidence/tests/test_credential_pure.py` y `tests/integration/test_credential.py`: `did:web`, lista de estado (orden de bits, GZIP, base64url), sujeto sin datos personales, verificación contra el DID, revocación que invalida sin tocar la credencial, lista falsificada o clave ajena rechazadas, emisión real con la clave de Vault, idempotencia y tablas de escritura única.
- `services/evidence/tests/test_edc_pure.py` y `tests/integration/test_edc.py`: cada política de la biblioteca se lee sin cláusulas no verificables; activo, política y contrato aceptados por la API simulada con la clave; republicar no es un error; una clave errónea se rechaza; el expediente no puede salir por el conector; la publicación queda registrada una vez y anotada en el diario.
- `tests/integration/test_evidence_workflow.py`: la cadena completa termina en una credencial que el comprobador público verifica sin reservas; un fallo a mitad y dos ejecuciones dejan una sola versión de cada objeto; un sello tardío hace un expediente nuevo y revoca la credencial anterior por sustituida; un sello que no llega deja un expediente honesto con una sola credencial.
- `tests/integration/test_evidence_containers.py`: con los contenedores, una campaña sellada y anunciada en NATS (dos veces) termina en una credencial que verifica con el DID y la lista de estado que publica `evidence-api`; la API no sirve expedientes ni credenciales desconocidas; un anuncio de una campaña ajena no arranca nada.
- `tests/integration/test_worm_conformance.py`: la prueba de conformidad de ADR-0010 contra el almacén real (borrar, sobrescribir y acortar la retención fallan).
- `tests/architecture/test_worm_has_no_delete.py`: el cliente no expone ni alcanza ninguna primitiva de borrado, ni por nombre ni por acceso dinámico.

## 9. Limitaciones conocidas y pendientes

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
| 0.8.0-alpha | 2026-09-18 | Credencial verificable VC 2.0 con `eddsa-jcs-2022`, `did:web` y Bitstring Status List | F07-10 |
| 0.9.0-alpha | 2026-09-18 | Núcleo puro de verificación separado y paquete de verificación para el comprobador público | F07-11 |
| 0.10.0-alpha | 2026-09-18 | Publicación de la credencial en espacios de datos vía EDC con política ODRL verificable | F07-12 |
| 0.11.0-alpha | 2026-09-18 | Cierre de campaña encadenado (`EvidenceWorkflow`), worker disparado por el sello, API pública y contenedores | F07-13 |
| 0.12.0-alpha | 2026-09-21 | Lado de lectura para la API v1 (`argos_evidence.reads`): cadena (la misma función que embebe el expediente), artefactos paginados, artefacto con su prueba de inclusión, expediente vigente, vista previa exacta de la credencial y su estado; `EvidenceActivities` expone `store` y `dsn` | F08-07 |
| 0.13.0-alpha | 2026-09-22 | `reads.campaign_journal_entry` (el asiento del diario que cita un veredicto de la campaña, y ninguno más) y `credential.issue.WITHHELD` (lo que se queda en el expediente), que la vista previa de la credencial devuelve como `withheld` | F08-14 |
| 0.14.0-alpha | 2026-09-23 | Lista de estado con `validUntil` y firmada solo cuando cambia, 404 para listas inexistentes, `did:web` estricto, límites de base58 y de descompresión, `trust_anchors()` | F09-20 |
| 0.15.0-alpha | 2026-09-23 | Contenedores con la postura restringida de ARG-084 y perfil seccomp propio | F09-03 |
| 0.16.0-alpha | 2026-09-23 | Usuario de base `login_evidence` en `svc_evidence` para el worker y la API; contraseña en fichero de secreto | F09-04 (ARG-085) |
| 0.17.0-alpha | 2026-09-23 | `issued_by`: la credencial emitida desde la API asienta a la persona que la emite (SEC-030) | F09-26 (ARG-005, ARG-071) |
