# ADR-0011 · Credencial verificable: formato, firma, identidad y revocación

- **Estado:** Propuesta
- **Fecha:** 2026-09-17
- **Decide:** el usuario (tarea F07-00)
- **Contexto:** Fase 07 · Evidencia y credencial (ARG-068, ARG-069) · Pliego P-17

## Contexto

La credencial es el resumen firmado que viaja: qué organización, qué ámbito, qué campaña, qué resultado agregado, cuándo y verificado por qué appliance. Cualquier tercero tiene que poder comprobarla **sin contactar con nosotros y sin ver un solo dato del cliente**. El documento de fase fija el formato (W3C Verifiable Credentials 2.0 con *Data Integrity*) pero deja abiertas tres elecciones: el conjunto criptográfico, el método de identidad del emisor y el mecanismo de revocación.

## Decisión propuesta

1. **W3C Verifiable Credentials Data Model 2.0.**
2. **Conjunto criptográfico `eddsa-jcs-2022`** (*Data Integrity EdDSA Cryptosuites*): la forma canónica es JCS (RFC 8785, canonicalización de JSON), no RDF. Razones: el comprobador público puede ser un fichero pequeño sin procesador RDF; JCS es determinista y fácil de comprobar a mano; y la firma es Ed25519, la misma familia que la clave del appliance.
3. **Emisor `did:web`** del appliance: el documento DID publica la clave pública registrada en el alta (TPM en el appliance, Vault Transit en desarrollo). Un espacio de datos puede usar en su lugar el DID de su catálogo.
4. **Revocación con *Bitstring Status List*** (W3C): una lista de bits comprimida, publicada como credencial firmada por el comprobador. Revocar una credencial emitida sobre una campaña impugnada no toca la credencial.
5. **Nunca datos personales ni contenido del cliente**: el `credentialSubject` lleva el resultado agregado y el anclaje a la evidencia (raíz de Merkle, sello de tiempo), nada más. Un test de producto recorre la credencial emitida y falla si encuentra un valor con forma de identificador personal (los validadores de ARG-024).
6. **Alineación Gaia-X:** los atributos que esperan los catálogos federados se añaden como contexto propio, sin cambiar el núcleo. La validación contra las herramientas del GXDCH es una tarea manual (`F07-14`), porque exige el alta del participante.

## Consecuencias

- El comprobador público no necesita procesar RDF: verificar es canonicalizar con JCS, resolver la clave y comprobar la firma Ed25519.
- `did:web` exige que la clave pública sea publicable por HTTPS; en un appliance aislado, el documento DID viaja con el expediente y el comprobador lo acepta como anexo.

## Alternativas descartadas

- **`eddsa-rdfc-2022`** (canonicalización RDF): más interoperable con parte del ecosistema de datos enlazados, pero arrastra un procesador RDF al comprobador público, que tiene que ser mínimo.
- **JWT/SD-JWT como formato de la credencial:** válido, pero el documento de fase y la alineación Gaia-X apuntan a *Data Integrity*.
- **Revocación por consulta en línea al emisor:** rompe «verificar sin contactar con nosotros».
