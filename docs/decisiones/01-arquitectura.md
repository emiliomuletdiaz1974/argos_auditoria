# 01 · Decisiones de arquitectura (ADR)

**Confidencialidad:** `internal` · [← índice](README.md)

Una ficha por ADR con el mismo formato:

- **Decidimos:** qué se decidió.
- **Por qué:** los motivos.
- **Qué comprobamos antes:** lo que se verificó antes de decidir. Si no quedó comprobación escrita, se dice.
- **Descartamos:** las alternativas que se rechazaron.
- **Consecuencias:** qué implica la decisión.

El texto completo está en `docs/adr/`.

---

## ADR-0001
**Alcance de la Fase 1 y estructura del monorepo** · Aceptado 2026-09-14 (E0-03)

- **Decidimos:**
  - Los documentos de fase mandan en numeración, contenido de componentes y rutas; el Plan Director manda en orden, método, calendario y definición de hecho.
  - El monorepo sigue la estructura de ARG-001 (`libs/`, `services/`, `connectors/`, `console/`, `platform/`, `library/`, `tools/`, `deploy/dev/`, `tests/`, `docs/`).
  - ARG-002 (imagen Packer) y ARG-003 (k3s) se aplazan hasta que llegue el hardware. Mientras tanto usamos Docker Compose con los mismos servicios.
- **Por qué:** el Plan y el documento de la Fase 01 numeraban y estructuraban de forma distinta, y necesitábamos una sola regla para resolver los choques. Sin el Servidor Cognitivo no hay forma real de probar ni el arranque medido ni los drivers de GPU.
- **Qué comprobamos antes:** el código que ya había en `argos/` seguía la estructura de ARG-001.
- **Descartamos:**
  - La estructura del Plan en castellano: obligaba a reescribir las rutas de los 100 componentes y a mantener dos nomenclaturas.
  - Construir ya Packer y k3s: sin hardware no se podía probar.
- **Consecuencias:** la Fase 1 se cierra sin hardware; ARG-002/003 quedan como tareas MANUAL `F1-11a` y `F1-11b`. La carpeta `platform/` todavía no existe: la crea la Fase 09.

## ADR-0002
**Diario encadenado v1** · Aceptado 2026-09-14 (E0-03)

- **Decidimos:**
  - Tabla `argos.audit_journal` con `seq` contiguo, sin IDENTITY.
  - Formas canónicas guardadas (`at_canon`, `payload_canon`).
  - Hash `SHA-256("ARGOS-JOURNAL-v1" ‖ u64be(seq) ‖ campos con prefijo de longitud ‖ prev_hash)`.
  - Escritura solo por `argos.journal_append`, con bloqueo consultivo, `SECURITY DEFINER` y `search_path` fijo.
  - Triggers que impiden UPDATE, DELETE y TRUNCATE.
  - Un verificador independiente en Python y vectores de prueba compartidos.
- **Por qué:** había tres definiciones incompatibles del diario (librería común, ARG-005 y ARG-066): el verificador de ARG-066 habría marcado como corrupto todo lo escrito por ARG-005. Además, hashear `jsonb::text` depende de cómo normalice cada versión del motor.
- **Qué comprobamos antes:** analizamos los defectos concretos de ARG-005:
  - concatenar sin separador es ambiguo;
  - `FOR UPDATE` no bloquea nada con la tabla vacía, así que la cadena se bifurca con inserciones concurrentes;
  - IDENTITY deja huecos tras un rollback;
  - `SECURITY DEFINER` sin `search_path` se puede secuestrar;
  - `TRUNCATE` estaba permitido.
  - Calculamos a mano los vectores del diario antes de escribir el código.
- **Descartamos:**
  - IDENTITY: sus huecos no se distinguen de una supresión.
  - Hashear el texto que genera el motor.
  - Calcular el hash en el cliente e insertar después.
- **Consecuencias:** cambiar la fórmula exige una v2 con un asiento de transición; nunca se reescribe. Todos los componentes escriben con `PostgresJournal`.

## ADR-0003
**Herramientas y CI** · Aceptado 2026-09-14 (E0-03)

- **Decidimos:**
  - Python 3.12 con **uv** (workspace y `uv.lock` versionado), ruff, mypy estricto, pytest-cov y gitleaks.
  - `make` como interfaz única.
  - GitHub Actions con las etapas de ARG-010.
  - Tests de integración marcados con `@pytest.mark.integration`.
- **Por qué:**
  - pip no ofrece un lockfile reproducible por componente.
  - El proyecto vive en GitHub (Plan Director §9.2 y §16), y montar un GitLab autoalojado antes de tener código era infraestructura que operar sin beneficio.
- **Qué comprobamos antes:** `argos/` usaba pip sin lockfile y ruff no estaba instalado; ARG-001/010 pedían GitLab y el Plan usaba GitHub.
- **Descartamos:** pip con requirements; GitLab autoalojado ya.
- **Consecuencias:** nota ARG-010 (de GitLab a GitHub Actions); el CI se puede portar a un runner autoalojado.

## ADR-0004
**Versión base de la web comercial** · Aceptado 2026-09-14 (E0-03) · también en `argos-web/docs/adr/`

- **Decidimos:** partir de la **v7_1**.
- **Por qué:**
  - La v7_1 ya trae el bloque legal obligatorio (LSSI-CE art. 10, RGPD art. 13) y las mejoras P1–P3 probadas.
  - Portar ese bloque a mano a la v6, dentro de un `index.html` de unos 300 KB, tiene riesgo de error y no aporta nada al backend.
- **Qué comprobamos antes:**
  - Solo v4 y v7_1 estaban desempaquetadas; v6 y v7 estaban dentro del ZIP.
  - Los seis PHP son idénticos en v4, v6, v7 y v7_1; las diferencias están solo en `index.html` y en los ficheros de SEO.
- **Descartamos:** la v6 con el bloque legal portado, que es lo que decía el Plan Director.
- **Consecuencias:** se publican también las FAQ, los sectores y WhatsApp. Hay que revisar los plazos de conservación de la política de privacidad frente a la purga de W-07.

## ADR-0005
**Idioma del código** · Aceptado 2026-09-14 (a raíz de F1-07)

- **Decidimos:**
  - Todo el código de `argos/` en inglés: identificadores, ficheros, comentarios, logs, tests, claves JSON, endpoints y valores de base de datos.
  - La documentación y git, en español.
  - `argos-web/` se queda como está.
  - Los nombres exactos se fijan en un glosario.
- **Por qué:** convivían dos idiomas, porque el esquema SQL y el código de referencia de los documentos ya estaban en inglés, y seguir así solo aumentaba la mezcla.
- **Qué comprobamos antes:** el código anterior a F1-06 estaba en español; era el momento más barato de cambiar.
- **Descartamos:**
  - Identificadores en inglés con comentarios en español: mezcla dos idiomas en el mismo fichero.
  - Migrar solo lo nuevo: meses con dos convenciones.
- **Consecuencias:** un refactor único (R-01) y reescribir los planes (R-02). La migración `0001` se renombró y se recreó la base de desarrollo. La fórmula del diario no cambió.

## ADR-0006
**Pila de la ontología** · Aceptado 2026-09-16 (F04-00, con un cambio sobre la propuesta)

- **Decidimos:**
  - rdflib 7 en proceso, con los quads persistidos por versión en PostgreSQL (`Dataset`, no `ConjunctiveGraph`).
  - pySHACL 0.40 sin inferencia.
  - Servidor OPA con Rego v1 y `opa test`.
  - Bundles `tar.gz` deterministas firmados con Ed25519 en Vault (`argos-content`, clave separada de la de release).
  - Las cinco puertas editoriales del Plan Director.
  - Núcleo en inglés con una **capa de traducción** cerrada para las claves del jurista.
- **Por qué:**
  - Un almacén de triples dedicado sería el cuarto almacén para solo 50–100 mil triples.
  - OPA en servidor es la forma documentada y la más fácil de depurar.
  - Separar las claves de contenido y de release permite rotarlas y custodiarlas por separado.
  - La plantilla editorial tiene que poder leerla un jurista.
- **Qué comprobamos antes:**
  - Sondas del 2026-09-16: rdflib 7.6.0 resuelve el SPARQL del resolutor, `from_n3` recupera cada término y el orden de N-Triples es estable.
  - pySHACL 0.40.1 aplica `sh:minCount` y `sh:in` como pide el documento.
  - `ConjunctiveGraph` está en desuso en rdflib 7.
  - La firma Ed25519 en Vault ya existía; no había cosign.
- **Descartamos:**
  - Fuseki o GraphDB.
  - Reglas en Python o en SHACL.
  - OPA embebido vía Wasm (una cadena de compilación más).
  - cosign ya (exige el binario en el appliance y un registro).
  - Una excepción a ADR-0005: la propusimos y **la rechazamos al aprobar**; la sustituimos por la capa de traducción.
- **Consecuencias:** un contenedor más (OPA) y ADR-0005 sin excepciones. **Pendiente de corregir:** la imagen de OPA está fijada por etiqueta y no por digest como dice el ADR (ver [revisión](04-revision-2026-09-23.md)).

## ADR-0007
**Motor de retos** · Aceptado 2026-09-17 (F05-00, con un cambio) · **sustituido en parte por ADR-0012**

- **Decidimos:**
  - DSL en YAML validado con JSON Schema 2020-12, en inglés con traducción al castellano.
  - Veredicto de cuatro valores: `compliant`, `non_compliant`, `not_demonstrated` e `inconclusive`.
  - Evaluador puro (sin E/S ni reloj), con `verdict_hash` y un test arquitectónico que impide que otro módulo escriba veredictos.
  - Contrato OPA `verdict.compliant`.
  - Campaña fijada a una instantánea, a una versión de ontología y a una de biblioteca.
  - Workflows en Temporal.
  - Hallazgos con máquina de estados.
  - **Sello de campaña ya en la Fase 05.**
- **Por qué:**
  - El Plan Director exige «no demostrado» cuando la cota de Wilson no permite absolver.
  - La prueba de la fase exige los mismos veredictos con la misma instantánea, cosa que el grafo vivo no garantiza, y también exige el sello.
- **Qué comprobamos antes:**
  - El documento usaba infraestructura inexistente (`argos_db`, `uuid.uuid7` de Python 3.14, `inventory_client`, `opa_client`).
  - Los paquetes OPA reales devuelven `verdict.compliant`.
  - Los roles del realm eran otros.
  - Recalculamos a mano el vector de muestreo del documento: da **370**, no 371.
- **Descartamos:**
  - Una gramática propia.
  - El veredicto binario (absuelve o condena sin base estadística).
  - El grafo vivo.
  - Dejar el sello para la Fase 07.
- **Consecuencias:** nuevas dependencias (`jsonschema`); migraciones desde la `0011`. La API de campañas que definía se retiró en F08-17 (ADR-0012).

## ADR-0008
**Sujeto sintético** · Aceptado 2026-09-17 (F05-00)

- **Decidimos:**
  - ARGOS **genera y registra** sujetos sintéticos con marcas verificables: DNI y NIE no expedidos, IBAN ficticio y `example.invalid`.
  - El **cliente los inyecta y ejercita** los derechos; un DPO autoriza y el cliente confirma por la API.
  - ARGOS verifica con sondas de conteo sobre hashes HMAC.
  - No se sella una campaña con sujetos sin revertir.
- **Por qué:**
  - Inyectar es escribir, y rompería el solo-lectura del producto.
  - Si ARGOS ejecutara la supresión, estaría verificando su propio proceso y no el del cliente.
- **Qué comprobamos antes:** el documento de la Fase 05 no tenía ningún componente para esto (lo añade el Plan Director), y el solo-lectura por construcción ya estaba probado por el arnés de F02-01.
- **Descartamos:**
  - Un conector con modo escritura: un selector erróneo escribiría en datos reales.
  - Custodiar credenciales de escritura: convertiría a ARGOS en actor del tratamiento que audita.
  - Prescindir del sujeto sintético: se pierde el reto canónico y la demo.
- **Consecuencias:** el solo-lectura se mantiene sin excepciones; una campaña puede durar días.

## ADR-0009
**Modelo local y servidor de inferencia** · Aceptado 2026-09-17 (F06-00)

- **Decidimos:**
  - El modelo es configuración (`ARGOS_LLM_LOCAL_ENDPOINT`, `ARGOS_LLM_MODEL`).
  - Qwen2.5-14B-Instruct AWQ de 4 bits (Apache 2.0) y embeddings `multilingual-e5-small` (MIT).
  - En desarrollo, llama.cpp en CPU con la misma API compatible con OpenAI.
  - Los tests usan un backend simulado y determinista.
  - Los pesos los descarga una persona y anota su hash.
- **Por qué:**
  - Licencia comercial permisiva, buen castellano, cabe en la talla S y soporta JSON guiado.
  - P-03 exige cero llamadas al exterior.
- **Qué comprobamos antes:** no hay servidor con GPU; P-03; la variable del endpoint ya existía desde la Fase 01.
- **Descartamos:**
  - Ollama: formato y API propios.
  - Un modelo de 1–3B: los conjuntos dorados dejarían de significar nada.
  - Un proveedor externo: rompe P-03.
- **Consecuencias:** en desarrollo es lento; el primer token en menos de 2 s se mide en F06-98 con GPU.

## ADR-0010
**Almacén WORM de la evidencia** · Aceptado 2026-09-18 (F07-00)

- **Decidimos:**
  - La garantía la da **una prueba de conformidad**, no la documentación del producto: borrar, sobrescribir y acortar la retención tienen que fallar.
  - Solo licencias permisivas o LGPL, nunca AGPL.
  - Orden de candidatos: VersityGW → SeaweedFS → Ceph RGW.
  - Dos buckets: `evidence` en conformidad a 10 años y `working`.
  - Cliente sin método de borrado; almacén sobre LUKS2.
- **Por qué:**
  - Un perito tiene que poder citar una garantía que no dependa de nuestro código.
  - El appliance se entrega al cliente, así que la AGPL nos obligaría.
- **Qué comprobamos antes:** una tabla de licencias y soporte de object lock:
  - MinIO y Garage son AGPL, y Garage además no lo soporta.
  - Ceph es LGPL y pesado.
  - Resultado del 2026-09-18: VersityGW v1.8.0 **pasa** `test_worm_conformance.py`.
- **Descartamos:**
  - Triggers de PostgreSQL: no protegen frente a un administrador.
  - Firmar sin bloquear: detecta la manipulación pero no la impide.
- **Consecuencias:** el superusuario del sistema de ficheros queda fuera de la garantía; lo cierran el cifrado y el endurecimiento (F1-11a y Fase 09).

## ADR-0011
**Credencial verificable** · Aceptado 2026-09-18 (F07-00)

- **Decidimos:**
  - VC 2.0 con Data Integrity `eddsa-jcs-2022`.
  - Emisor `did:web`.
  - Revocación con Bitstring Status List.
  - Ningún dato personal en la credencial (lo comprueba un test).
  - Contexto propio para Gaia-X.
- **Por qué:**
  - Con JCS el comprobador no necesita un procesador RDF, el resultado es determinista y se puede comprobar a mano.
  - Ed25519 es la misma familia que la clave del appliance.
  - Verificar tiene que ser posible sin contactarnos.
- **Qué comprobamos antes:** el documento fijaba VC 2.0 con Data Integrity y dejaba abiertos la suite criptográfica, el DID y la revocación.
- **Descartamos:**
  - `eddsa-rdfc-2022`: arrastra un procesador RDF.
  - JWT o SD-JWT: el documento y Gaia-X apuntan a Data Integrity.
  - Revocación consultando en línea al emisor.
- **Consecuencias:** el registro en un GXDCH es la tarea manual F07-14 y no bloquea `fase-07`.

## ADR-0012
**API única** · Aceptado 2026-09-20 (F08-00)

- **Decidimos:**
  - Una sola API autenticada, `argos-api` bajo `/api/v1`, que llama en proceso a las librerías del dominio (el gateway de IA, por HTTP).
  - Se retira `challenge-api`.
  - `evidence-api` y el comprobador se quedan aparte.
  - GraphQL del grafo en `/api/v1/inventory/graph`.
  - Cursor opaco, errores RFC 9457, `Idempotency-Key` y contrato OpenAPI generado del código.
  - Cada mutación deja su asiento en el diario.
- **Por qué:**
  - Dos APIs sobre el mismo dominio son «dos verdades», y el documento lo prohíbe.
  - Así hay un solo contrato y un solo sitio de autorización.
  - El material público no debe abrir rutas dentro de la API autenticada.
  - REST no sirve para navegar vecindarios de un grafo.
- **Qué comprobamos antes:** inventario de las APIs existentes y sus puertos (8003, GraphQL, 8005, 8008 y 8007).
- **Descartamos:**
  - Una API por servicio.
  - Una pasarela HTTP: capa extra y latencia.
  - GraphQL para todo: el cliente integra por REST.
- **Consecuencias:** en F08-17 se movieron a la API única las rutas que solo vivían en `challenge-api`.

## ADR-0013
**Consola** · Aceptado 2026-09-20 (F08-00)

- **Decidimos:**
  - React (lo fija el documento) con Vite y **TypeScript estricto**.
  - Tipos generados del contrato con `openapi-typescript`.
  - Pruebas con Vitest, Playwright y stylelint (la regla del dorado).
  - npm con lockfile.
  - Estáticos servidos por la API única.
  - Sesión OIDC con PKCE; token en memoria y refresco en una cookie `HttpOnly`.
  - Accesibilidad AA probada con tests.
- **Por qué:**
  - El tipado estricto es regla de la casa.
  - Con los tipos generados, un cambio en la API rompe la compilación de la consola en vez de romper la pantalla del DPO.
  - P-03 prohíbe CDN.
- **Qué comprobamos antes:** el documento fija React sin CDN; el Plan §9.3 dice que el marco que fija el documento se respeta; la máquina tiene Node v26.
- **Descartamos:**
  - JSX sin tipos.
  - Next.js: otro servidor que operar.
  - Cypress.
  - CDN.
- **Consecuencias:** dos cadenas de herramientas; `make check` incluye `console-*`.

## ADR-0014
**Seguridad de plataforma sin appliance** · Aceptado 2026-09-23 (F09-00)

- **Decidimos:** tres niveles de trabajo.
  - **Ya, en el compose:** postura de contenedores, roles de PostgreSQL por servicio con credenciales dinámicas de Vault, mTLS, MFA, registro de seguridad, SBOM, actualizador, diagnóstico, backup y esclusa.
  - **Ya, validado en estático:** los manifiestos de k3s y `harden.sh`.
  - **Con hardware:** CIS real, arranque medido, TPM y aplicación en k3s.
  - Además:
    - la admisión del compose es un test;
    - una sola firma (la de release), y el SBOM entra en el manifiesto por su hash;
    - registro de seguridad en una tabla con su propia cadena;
    - TOTP para `platform_admin` y `dpo_reviewer`;
    - dossier contra ENS categoría media e ISO 27001:2022;
    - el cierre de la fase no espera al hardware.
- **Por qué:**
  - Esperar al hardware dejaría sin hacer justo lo que no depende de él y lo que la revisión de seguridad iba a encontrar primero.
  - Un log no se puede verificar como una cadena, y el ENS (op.exp.8) pide integridad del registro de actividad.
- **Qué comprobamos antes:**
  - Todos los servicios entraban a PostgreSQL como `argos` con `trust`; solo `argos_ai` estaba restringido.
  - Ningún contenedor declaraba usuario, `cap_drop` ni `read_only`.
  - El realm no pedía segundo factor.
  - Vault ya tenía PKI raíz e intermedia sin nadie que la usara.
  - La firma de release era Ed25519 en Vault, sin cosign ni registro.
- **Descartamos:**
  - Esperar al hardware.
  - k3s en una máquina virtual: no da TPM y duplica el entorno.
  - cosign con un registro en el compose.
  - Registro de seguridad en Loki.
- **Consecuencias:**
  - La migración de roles rompe los accesos cruzados entre servicios (es lo que buscamos).
  - El compose gana `cert-issuer` y el actualizador.
  - El dossier dirá claramente qué controles solo existen en desarrollo.
