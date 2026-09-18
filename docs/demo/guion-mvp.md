# Guion de la demostración del MVP auditable

Treinta minutos ante el equipo y los socios (Plan Director, Anexo F, hito S27). Es a la vez la prueba de aceptación del hito, material de formación comercial y ensayo del piloto. Todo lo que se enseña sale del **entorno de demostración sanitario** con sus hallazgos plantados, y todo se puede repetir con una orden.

> La consola llega con la Fase 08. Hasta entonces la demostración se hace en terminal con `make demo`, que deja cada salida en `.scratch/demo/` para abrirla durante la presentación. El resumen redactado por la IA local necesita los pesos del modelo (F06-05) y no forma parte de esta ejecución.

## Antes de empezar

| Qué | Orden | Qué debe verse |
|---|---|---|
| Entorno limpio, desde cero | `make demo-reset` | Todos los servicios sanos, las fuentes sembradas y la base migrada. Borra todos los volúmenes, incluidos el almacén WORM y la autoridad de sellado de pruebas |
| Ensayo completo | `make demo` | Seis bloques en pantalla y los ficheros de `.scratch/demo/` |
| Plan B preparado | `uv run python tools/verify_evidence.py docs/demo/respaldo/bundle.json` | `RESULT: verified` |

## Minuto a minuto

| Minuto | Bloque | Qué se hace | Qué debe verse | Salida |
|---|---|---|---|---|
| 0–3 | **El problema** | Dos diapositivas: la brecha entre lo declarado y lo efectivo, y el calendario normativo | Frase ancla: «Cumplimiento verificado, no declarado» | — |
| 3–8 | **ARGOS ve** | Inventario del entorno de demostración | `2 sistemas inventariados`; abrir `inventory.json` | `inventory.json` |
| | | El arnés intenta escribir en la fuente clínica | `rechazado`: solo lectura por construcción | — |
| 8–12 | **ARGOS sabe qué exigir** | Ontología cargada y aplicada a la instantánea | Las obligaciones de RGPD y AI Act que aplican, con su artículo fuente | `campaign.json` |
| 12–20 | **ARGOS reta** | Campaña con aprobación del DPO; el reto estrella es el borrado efectivo del sujeto sintético | `Campaña sellada con 12 hallazgos`; `dsr-erasure-effective` en la réplica de facturación: `non_compliant` (el dato reapareció en la réplica «plantada») | `campaign.json` |
| 20–26 | **ARGOS prueba** | Expediente: hallazgos, cadena de evidencia (raíz de Merkle, firma, sello, diario) | `Expediente <hash> con sello stamped`; abrir `dossier.pdf` y señalar el hash del pie y el QR | `dossier.pdf`, `dossier.json` |
| | | Credencial y comprobador público | `Paquete íntegro: verificado`; abrir `credential.json` y `report.json` | `credential.json`, `bundle.json`, `report.json` |
| | | Un byte corrupto en vivo | `Comprobaciones que fallan: artifact_inclusion[0]`: el comprobador dice qué pieza se tocó | `tampered-report.json` |
| 26–30 | **Lo que viene** | Los tres horizontes y el piloto | Cierre: «ARGOS no certifica, prepara» | — |

Mensajes que acompañan a cada bloque:

- **Ve:** cada nodo del inventario dice qué conector lo vio y cuándo; la instantánea queda fechada.
- **Sabe qué exigir:** el derecho hecho datos, con proceso editorial y un plazo de 30 días.
- **Reta:** «la IA propone, el motor dispone». El criterio del reto es Rego legible y una reejecución da el mismo veredicto.
- **Prueba:** evidencia que un auditor puede comprobar sin fiarse de nosotros. La firma y el sello de desarrollo se presentan como tales: no son cualificados.

## Plan B

Si la campaña en vivo tarda o falla, se enseña la **campaña precocinada** de `docs/demo/respaldo/`: el paquete de verificación completo (`bundle.json`) y el expediente en PDF (`expediente.pdf`), generados por este mismo guion. Se comprueba sin red con:

```
uv run python tools/verify_evidence.py docs/demo/respaldo/bundle.json
```

El paquete trae dentro el documento DID, la lista de estado y la raíz de la autoridad de sellado, así que verifica aunque el entorno esté parado. Para enseñar el byte corrupto con el plan B, basta con alterar un carácter de un artefacto del paquete y repetir la orden.

## Qué queda fuera de esta versión

- La **grabación** de la demostración y las **dos diapositivas** del bloque inicial las prepara una persona.
- El resumen redactado por la IA local, con su verificador de citas en verde, necesita los pesos del modelo (F06-05).
- La navegación por el grafo y por las obligaciones se hará en la consola (Fase 08).
