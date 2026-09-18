---
id: MOD-argos-evidence
kind: module
title: Servicio de evidencia (argos-evidence)
module: argos-evidence
phases: ["07"]
version: 0.1.0-alpha
commit: 771c9f3
date: 2026-09-18
status: draft
confidentiality: client
---

# Servicio de evidencia (argos-evidence)

## 1. Propósito

Convierte el resultado de una campaña en evidencia que un tercero puede comprobar sin fiarse de ARGOS: artefactos inmutables, un árbol de Merkle que los encadena, la firma de su raíz, un sello de tiempo, el expediente y la credencial verificable. Implementa ARG-061 a ARG-070.

En su estado actual contiene el **árbol de Merkle por campaña (ARG-063)** y el anclaje de su raíz. El resto llega en las tareas siguientes de la Fase 07, y este documento está en estado `draft` hasta entonces.

## 2. Alcance y límites

- **Hace:** construir el árbol sobre el SHA-256 de los artefactos de una campaña, dar la prueba de inclusión de cada uno, verificarla y señalar qué artefactos ya no coinciden; anclar la raíz de cada campaña una sola vez.
- **Hará:** almacén WORM (ARG-061), artefactos (ARG-062), firma (ARG-064), sellado temporal (ARG-065), anclaje del diario (ARG-066), expediente (ARG-067), credencial (ARG-068) y publicación en espacios de datos (ARG-070).
- **No hace:** no decide conformidad (eso es del evaluador del motor de retos) ni modifica una raíz ya anclada.

## 3. Arquitectura

- `argos_evidence.merkle`: el árbol. **Solo biblioteca estándar**: el mismo fichero se entrega junto al expediente como verificador aislado (`python merkle.py <artefacto> <prueba.json>`).
- `argos_evidence.roots`: orden de las hojas y anclaje de la raíz en PostgreSQL.

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
| Tabla o migración | `argos.campaign_roots` (`0021_campaign_roots.sql`) | Raíz, número de hojas, orden y clave del árbol en el WORM; se escribe una vez |
| Herramienta de línea de órdenes | `python merkle.py <artefacto> <prueba.json>` | Verificador aislado; código de salida 0 si el artefacto pertenece al árbol |

## 5. Configuración

No tiene configuración propia. Usa la cadena de conexión a PostgreSQL de la plataforma (`ARGOS_DATABASE_URL`, desde `argos-common`).

## 6. Seguridad y tratamiento de datos

- Solo maneja **hashes** de artefactos, nunca su contenido.
- `argos.campaign_roots` es de escritura única: un disparador rechaza `UPDATE`, `DELETE` y `TRUNCATE`.
- Decisiones aplicables: ADR-0010 (almacén WORM), ADR-0011 (credencial) y nota ARG-064-065.

## 7. Operación

Por ahora es una librería. El servicio y su contenedor llegan con F07-13.

## 8. Verificación

- `tests/unit/test_merkle_vectors.py`: vectores calculados con un script independiente (`tools/merkle_vectors.py`), sin compartir código con el árbol.
- `services/evidence/tests/test_merkle_pure.py`: vectores exactos; inclusión en árboles de 1 a 64 hojas; 2000 corrupciones de un byte con semilla fija, todas detectadas y localizadas.
- `services/evidence/tests/test_merkle_standalone_pure.py`: solo biblioteca estándar y verificador por línea de órdenes.
- `tests/integration/test_campaign_roots.py`: orden de las hojas y escritura única de la raíz.

## 9. Limitaciones conocidas y pendientes

- El árbol completo se guardará en el WORM cuando exista (F07-04); hasta entonces `tree_key` es solo la clave prevista.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-18 | Árbol de Merkle con separación de dominio, verificador aislado y anclaje de la raíz | F07-03 |
