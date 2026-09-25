---
id: RB-04
title: "El registro de seguridad avisa"
alerts: [SecurityChainBroken, SecuritySignatureRejected, SecurityRefusalBurst]
confidentiality: client
---
# RB-04 · El registro de seguridad avisa

## Síntoma

- `SecurityChainBroken` (crítica): la cadena del registro de seguridad no verifica. Alguien lo ha cambiado.
- `SecuritySignatureRejected` (crítica): se ofreció al appliance una release, un bundle de contenido o unas políticas que no verifican.
- `SecurityRefusalBurst`: más de 50 autenticaciones o permisos rechazados en 5 minutos. Alguien lo está intentando.

## Diagnóstico

1. Lee el registro de seguridad desde la consola (Seguridad) o por la API: `GET /api/v1/security/events`, filtrando por el tipo del aviso.
2. Para una firma rechazada, identifica qué se ofreció (release, contenido o políticas) y quién lo trajo (esclusa, operador).
3. Para una ráfaga, identifica el origen (usuario, dirección) y si alguna autenticación llegó a entrar.

```bash
curl http://127.0.0.1:8000/metrics
```

## Acción

- **Cadena rota:** como RB-01. No toques nada, congela una copia (`make backup`) y avisa.
- **Firma rechazada:** no reintentes la carga. Retira el soporte de la esclusa y guarda el fichero rechazado para el análisis.
- **Ráfaga de rechazos:** bloquea la cuenta u origen en el directorio del organismo si es un ataque. Si es un error de configuración de una integración, corrígelo.

## Verificación

- La alerta se resuelve, y el registro de seguridad vuelve a verificar (`argos_security_chain_ok` a 1).
- La firma rechazada tiene explicación escrita: quién la trajo y por qué no verificaba.

## Cuándo escalar

La cadena rota y la firma rechazada siempre: al responsable de seguridad del organismo y al soporte de ARGOS. La ráfaga, si alguna autenticación indebida llegó a entrar.
