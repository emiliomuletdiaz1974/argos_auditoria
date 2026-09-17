# ADR-0008 · Sujeto sintético sin romper el solo-lectura (Fase 05)

**Estado:** Propuesta · 2026-09-17 · Aaron Escobar

## Contexto
El Plan Director (§8.2, Fase 05, bloque 1) pone el **sujeto sintético** en el centro del producto:
- identidades y datos de prueba generados y marcados;
- inyectados de forma controlada y reversible **solo donde el cliente lo autoriza**;
- un inventario de sujetos que es en sí un artefacto auditado.

El reto canónico es el **borrado efectivo**: se ejercita el derecho de supresión de un sujeto sintético y días después ARGOS verifica que el dato no reaparece en réplicas, cachés ni restauraciones.

El documento de la Fase 05 no tiene componente para el sujeto sintético, y el concepto choca con un principio vigente:
- **Solo-lectura por construcción (§7.2 del Plan Director, ARG-011):** los conectores no pueden escribir; el arnés de escritura de F02-01 lo prueba. Inyectar un sujeto en el sistema del cliente es una escritura.
- **Ejercicio del derecho:** la supresión la ejecuta el cliente por su canal (portal, formulario, procedimiento interno). Si ARGOS la ejecutara, no verificaría el proceso del cliente, sino el suyo.

## Decisión (propuesta)
- **ARGOS genera y registra; el cliente inyecta y ejercita.** Ningún paquete del producto escribe en sistemas del cliente, y los conectores siguen siendo de solo lectura.
- **Generación (`argos_challenges.synthetic`):** identidades con **marcas verificables**:
  - DNI y NIE en rangos no expedidos, con letra de control válida;
  - IBAN con código de entidad ficticio;
  - correo en `example.invalid`;
  - nombre con prefijo reservado;
  - una semilla por campaña, para que la misma campaña genere los mismos sujetos.
- **Inventario auditado:**
  - `argos.synthetic_subjects`, con la identidad y los hashes de sus valores; los valores en claro solo en el paquete que recibe el cliente;
  - `argos.synthetic_injections`: punto de inyección autorizado, quién lo autorizó, método, confirmación del cliente, fecha de reversión;
  - asientos en el diario en cada paso: `synthetic.generate`, `synthetic.authorize`, `synthetic.injected`, `synthetic.revert`.
- **Autorización y confirmación:**
  - un `dpo_reviewer` autoriza cada punto de inyección en la API de campañas;
  - el cliente confirma la inyección y el ejercicio del derecho, también por la API, con usuario identificado;
  - sin confirmación, los retos con `preconditions: [synthetic_subject_injected]` quedan `inconclusive`, nunca `compliant`.
- **Verificación de solo lectura:** los retos (por ejemplo `dsr-erasure-effective` y `dsr-access-request-term`) buscan el sujeto con sondas `count` sobre los **hashes** de sus valores con la clave HMAC del sistema, sin traer datos. La verificación diferida se programa en la campaña como una unidad con fecha mínima.
- **Reversibilidad:** cada inyección lleva su procedimiento de reversión en el paquete del cliente, y la campaña no se sella con sujetos sin revertir o sin excepción documentada.
- **Demostración:** un script de desarrollo `tools/demo_client_actions.py`, fuera de los paquetes del producto, hace de cliente con las credenciales de propietario de las fuentes simuladas:
  - inyecta el sujeto en `clinic` y en la réplica `billing.patient_mirror`;
  - ejecuta la supresión solo en `clinic`;
  - deja el sujeto **plantado** en la réplica.

## Consecuencias
- El principio de solo-lectura se mantiene sin excepciones, y el arnés de escritura de F02-01 sigue siendo válido.
- El reto de borrado efectivo mide el proceso real del cliente, que es lo que promete el producto.
- Aparece un flujo con el cliente en la consola (Fase 08): paquete de inyección, confirmaciones y reversión. La Fase 05 lo expone por API.
- La campaña puede durar días: la verificación diferida vive en el workflow de Temporal, que ya lo soporta.

## Alternativas descartadas
- **Conector con modo escritura limitado a sujetos sintéticos:** rompe el solo-lectura por construcción y el arnés que lo prueba; un error de selector escribiría en datos reales.
- **Inyectar mediante la API del cliente con credenciales de escritura custodiadas por ARGOS:** mismo problema de principio, y convierte a ARGOS en actor del tratamiento que audita.
- **Sin sujeto sintético (solo retos pasivos):** deja fuera el reto canónico del producto y la demo del MVP (Anexo F del Plan Director).
