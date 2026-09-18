---
id: MOD-argos-connector-ldap
kind: module
title: Conector LDAP y Active Directory (argos-connector-ldap)
module: argos-connector-ldap
phases: ["02"]
version: 0.1.0-alpha
commit: cf0fd35
date: 2026-09-18
status: current
confidentiality: client
---

# Conector LDAP y Active Directory (argos-connector-ldap)

## 1. Propósito

Lectura del directorio corporativo:
- cuentas y sus estados;
- antigüedad de contraseñas y de últimos accesos;
- grupos y membresía transitiva.

Alimenta los retos de accesos y el grafo de identidades del inventario. Implementa ARG-018.

## 2. Alcance y límites

- Consulta el directorio sobre LDAPS; nunca modifica entradas.
- Devuelve agregados y muestras minimizadas, no listados completos de datos personales.

## 3. Arquitectura

- **`LdapConnector`:** conector del SDK para sistemas de tipo `directory`.
- **Conexión:** LDAPS con validación del certificado frente a una CA configurada y opción `read_only` de la librería. Si la sesión no queda en solo lectura, se aborta.
- **Consultas:**
  - agregados de cuentas;
  - recuentos con filtros validados (`validate_ldap_filter`);
  - muestras de antigüedad;
  - membresía transitiva recorriendo grupos, con detección de ciclos y un tope de nodos (`MAX_GROUP_NODES`).

## 4. Interfaces

Sondas del SDK: `scan_schema`, `count` y `sample`.

## 5. Configuración

- **Por sistema:** `base_dn`, `ca_file`, `tls_valid_names`, `user_filter`, `group_filter`, `page_size`, `connect_timeout_s` (10 s por defecto), `receive_timeout_s` (30 s por defecto) y `max_group_reads` (1000 por defecto).
- **Credenciales de enlace:** en Vault.

## 6. Seguridad y tratamiento de datos

**Permisos que necesita la cuenta del cliente:** una cuenta de servicio con **lectura** sobre la base de búsqueda (usuarios, grupos y atributos de estado). No necesita permisos de escritura ni de administración.

- Los filtros LDAP se validan antes de usarse, para evitar inyección.
- El recorrido de grupos está acotado: cada miembro es una búsqueda contra el controlador de dominio, todas bajo el único permiso de la sonda, así que la expansión se detiene tras `max_group_reads` lecturas.
- **No se siguen referrals.** Un referral a otro servidor recibiría el enlace con la contraseña de la cuenta de servicio, y en claro si fuera `ldap://`. Las entradas fuera del controlador configurado no se consultan.
- La conexión y cada respuesta tienen tiempo máximo, así que un servidor lento no bloquea al worker.

## 7. Operación

La paginación (`page_size`) evita consultas masivas contra el controlador de dominio.

## 8. Verificación

- **Tests unitarios:** `connectors/ldap/tests/test_ldap_connector.py`.
- **Test de integración:** `tests/integration/test_ldap_source.py`.
- **Evidencia de «sin escrituras»:** tras la prueba de la Fase 02, ninguna entrada tiene `modifyTimestamp` ni `createTimestamp` posteriores a su inicio.

## 9. Limitaciones conocidas y pendientes

Ninguna específica del conector.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-15 | Conector LDAP y Active Directory con membresía transitiva y conexión de solo lectura | Fase 02 (ARG-018) |
| 0.1.0-alpha | 2026-09-18 | Sin seguimiento de referrals y con tiempos máximos de conexión y respuesta | Auditoría de seguridad (A2) |
| 0.1.0-alpha | 2026-09-18 | Tope configurable de lecturas en la expansión de grupos (`max_group_reads`) | Auditoría de seguridad (M11) |
