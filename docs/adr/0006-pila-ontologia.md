# ADR-0006 · Pila de la ontología normativa (Fase 04)

**Estado:** Aceptado · 2026-09-16 · Aaron Escobar (con un cambio sobre la propuesta: capa de traducción en lugar de excepción a ADR-0005)

## Contexto
La Fase 04 (ARG-031…040) convierte la norma en datos: un esquema OWL de tres planos, un almacén RDF versionado, formas SHACL, políticas ODRL 2.2, reglas OPA/Rego, una matriz de trazabilidad, un flujo editorial con cinco puertas de CI y una publicación firmada. El documento de fase asume varias piezas que no existen en la plataforma o que chocan con decisiones vigentes:

- **Librerías:** `rdflib` (con `ConjunctiveGraph`), `pyshacl` y un sidecar OPA en `localhost:8181`, sin fijar versiones.
- **Firma:** `cosign sign-blob` con `hashivault://argos-content` y verificación con un binario `cosign` en el appliance. La plataforma firma hoy con Ed25519 en Vault Transit (ARG-010, `argos_common.release`) y cosign quedó aplazado a las Fases 9–10 (nota `ARG-010.md`).
- **CI:** un fichero `platform/ci/editorial.yaml` con sintaxis de GitLab; la CI del proyecto es GitHub Actions (ADR-0003).
- **Plantilla editorial:** claves YAML en castellano (`norma`, `articulo`, `vigente_desde`…) porque la legibilidad para juristas es requisito de producto; ADR-0005 fija las claves JSON en inglés.
- **Nombres:** categorías, clases de activo, paquetes Rego y valores (`categoria_especial.salud`, `package argos.retencion`, `"prohibida" "alto"`) en castellano, frente al código y los valores en inglés de ADR-0005 y del grafo de la Fase 03.

Sondas del 2026-09-16 en un entorno aislado con Python 3.12: rdflib 7.6.0 resuelve el SPARQL del resolutor, `from_n3(o.n3())` recupera cada término y la serialización N-Triples ordenada es estable; pySHACL 0.40.1 aplica `sh:minCount` y `sh:in` como espera el documento. En rdflib 7, `ConjunctiveGraph` está en desuso a favor de `Dataset`.

## Decisión
- **RDF y SPARQL:** `rdflib>=7.6,<8` en proceso, con persistencia en PostgreSQL (tablas de quads por versión de bundle, como propone ARG-032). Sin triplestore dedicado. `Dataset` en lugar de `ConjunctiveGraph`.
- **SHACL:** `pyshacl>=0.40,<0.41` en proceso, con `inference="none"`; el razonamiento costoso se materializa en la CI editorial.
- **Reglas operativas:** OPA como **servidor** (imagen oficial `openpolicyagent/opa`, fijada por digest en su tarea) al lado de los servicios, con Rego v1 y la API `/v1/data`; en desarrollo, un contenedor en `deploy/dev/compose.yaml`. El cliente es `httpx` y los tests de Rego se ejecutan con `opa test` dentro del contenedor.
- **Firma de bundles:** Ed25519 en **Vault Transit** con una clave propia `argos-content`, separada de `argos-release` (rotación y custodia independientes), reutilizando `VaultTransitSigner` y `verify_signature` de `argos_common.release`. El appliance verifica con la clave pública de contenidos incluida en la imagen. Sin cosign hasta que llegue con ARG-086/087.
- **Bundle:** `tar` determinista (orden de nombres, `mtime` y propietario fijos) con `manifest.json` de hashes SHA-256 por fichero; el manifiesto canónico es lo que se firma.
- **CI editorial:** las cinco puertas como un único punto de entrada `tools/ontology_gates.py` (con `make ontology-gates`) y un job en `.github/workflows/ci.yml` que se activa con cambios en `library/`.
- **Idioma:**
  - el vocabulario, las clases, las propiedades, los identificadores (`OBL-*`, `AC-*`, `CH-*`), los valores enumerados (`critical`, `high`, `medium`, `low`), los paquetes Rego y los selectores van **en inglés** y usan las categorías reales del grafo (`special_category.health`);
  - las **etiquetas legibles** (`rdfs:label`, mensajes SHACL) van con etiqueta de idioma, al menos `@es`;
  - **sin excepciones a ADR-0005:** el esquema, los modelos y los parsers internos trabajan solo con claves y valores en inglés (`norm`, `article`, `title`, `in_force_from`, `severity`, `applies_to`, `verified_by`, `equivalences`, `verification_pending`);
  - **capa de traducción para juristas:** un módulo aparte (`argos_ontology.editorial.translation`) traduce los campos de la plantilla que edita un jurista (`norma`, `articulo`, `titulo`, `vigente_desde`, `severidad`, `aplica_a`, `verificado_por`, `equivalencias`, `pendiente_verificacion`) a las claves internas en inglés antes de validar, y de vuelta al generar una plantilla para editar. El mapeo es una tabla cerrada y biyectiva: una clave que no está en ella es un error, nunca se ignora. El núcleo no conoce ninguna clave en castellano.
- **Paquete:** servicio `services/ontology` con distribución `argos-ontology` y paquete `argos_ontology`; contenido editorial en `library/ontology/` y `library/policies/`.

## Consecuencias
- Nuevas dependencias en `argos-ontology`: `rdflib`, `pyshacl`, `pyyaml` y `httpx` (las dos últimas ya están en el workspace).
- Un contenedor más en `make dev` (OPA, unas decenas de MB de RAM).
- En Vault de desarrollo, una clave de transit `argos-content`; el script de siembra de Vault la crea igual que `argos-release`.
- ADR-0005 se cumple sin excepciones: el castellano de la plantilla editorial vive solo en la capa de traducción, que tiene sus propios tests (ida y vuelta, claves desconocidas y claves duplicadas).
- Cuando cosign llegue (ARG-086/087), la firma de contenidos podrá migrar sin cambiar el formato del bundle: el manifiesto firmado es el mismo.

## Alternativas descartadas
- **Triplestore dedicado (Fuseki, GraphDB):** un cuarto almacén para 50–100 mil triples; coste operativo sin beneficio.
- **Reglas operativas en Python o en SHACL:** Python las saca del ciclo editorial; SHACL no encaja con decisiones parametrizadas por cliente.
- **OPA embebido vía WebAssembly:** añade una cadena de compilación de Rego a Wasm y un runtime; el servidor es la forma documentada y más fácil de depurar.
- **cosign ya en la Fase 04:** exigiría el binario en el appliance y un registro; se hereda la firma Ed25519 que ya verifica el appliance.
- **Plantilla editorial con claves en inglés y sin traducción:** rompe el requisito de producto de que un jurista la lea y la edite sin ayuda.
- **Excepción a ADR-0005 para las claves de la plantilla** (propuesta inicial): rechazada en la aprobación; el castellano mezclado en el núcleo del parser se sustituye por la capa de traducción.
