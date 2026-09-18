# ADR-0010 · Almacén WORM de la evidencia

- **Estado:** Propuesta
- **Fecha:** 2026-09-17
- **Decide:** el usuario (tarea F07-00)
- **Contexto:** Fase 07 · Evidencia y credencial (ARG-061) · Pliego P-15 y P-16 · Especificación Técnica §4

> El plan de la Fase 07 pedía este ADR con el número 0007, que ya ocupa el motor de retos. Se numera 0010.

## Contexto

La evidencia es lo que ARGOS vende, y su inmutabilidad tiene que ser **técnica, no una promesa de software propio**: un perito tiene que poder citar una garantía que no dependa de que nuestro código se porte bien. La herramienta estándar es un almacén compatible con S3 con *object lock* en **modo conformidad**: mientras dura la retención, nadie —tampoco el administrador del almacén— puede borrar ni acortar el plazo de un objeto.

La Especificación (§4) deja abierta la elección entre almacenes autoalojables, con la licencia por evaluar. El appliance es un producto que se entrega al cliente, así que la licencia importa tanto como la función.

## Opciones

| Almacén | Licencia | *Object lock* en conformidad | Observaciones |
|---|---|---|---|
| **MinIO** | AGPL-3.0 | Sí, maduro | La AGPL en un producto que se entrega obliga a publicar el código de lo que lo modifique o enlace; además, la edición comunitaria ha ido perdiendo funciones. **Descartado por licencia.** |
| **Garage** | AGPL-3.0 | No lo ofrece, según su documentación | Descartado por licencia y por función. |
| **Ceph RGW** | LGPL | Sí, maduro | Robusto, pero pesado para la talla S del appliance: un clúster para guardar evidencia. |
| **SeaweedFS** | Apache-2.0 | Soporte añadido en versiones recientes | Ligero. **El modo conformidad hay que comprobarlo, no suponerlo.** |
| **VersityGW** | Apache-2.0 | Declara soporte de *object lock* | Ya corre en el entorno de desarrollo como fuente S3 simulada. **Mismo requisito: comprobarlo.** |

## Decisión propuesta

1. **La garantía no se da por la documentación de nadie: la da una prueba de conformidad que es producto.** `F07-04` escribe un test que, contra el almacén real del entorno, sube un objeto con retención en modo conformidad y exige que **fallen** tres cosas: borrarlo, sobrescribirlo y acortar su retención. El almacén que no pase esa prueba no se usa, diga lo que diga su documentación.
2. **Licencia permisiva o LGPL**, nunca AGPL: el appliance se entrega al cliente.
3. **En desarrollo, VersityGW** (Apache-2.0, ya en el `compose`) como primer candidato, sometido a la prueba de conformidad. Si no la pasa, SeaweedFS; y si ninguno de los dos la pasa, Ceph RGW, aceptando su peso. La elección para el appliance es la que pase la prueba, y queda anotada en este ADR.
4. **Dos buckets**, como diseña el documento de fase: `evidence` (*object lock* en conformidad, retención por contrato, por defecto 10 años) y `working` (versionado sin bloqueo, expiración a 1 año).
5. **El módulo cliente no tiene método de borrado**: como el conector DICOM, la ausencia de la primitiva es la garantía en el lado del código. Un test arquitectónico lo vigila.
6. El almacén vive sobre el volumen cifrado del appliance (LUKS2, F1-11a).

## Consecuencias

- La inmutabilidad se puede demostrar en el entorno de desarrollo y en el appliance con la misma prueba, y un perito puede citarla.
- Elegir con una prueba y no con una tabla cuesta una tarea más, pero evita construir la cadena de evidencia sobre una garantía que el almacén no daba.
- Un objeto con retención de 10 años no se puede limpiar: el entorno de desarrollo usa retenciones cortas (minutos) para que se pueda resetear, y así se documenta en el kit de la demo (`F07-98`).

## Alternativas descartadas

- **Inmutabilidad en PostgreSQL con triggers** (como el diario): protege frente a nuestro código, no frente a un administrador de la base. No es la garantía que pide un perito.
- **Firmar y no bloquear:** la firma detecta la manipulación, pero no la impide; el borrado de una evidencia firmada también es una pérdida.
