---
id: RB-11
title: "Renovar los certificados externos"
procedure: true
confidentiality: client
---
# RB-11 · Renovar los certificados externos

## Síntoma

Los certificados internos se renuevan solos (RB-06). Los externos no: los que presenta la consola a los usuarios del organismo y los que el organismo emite para ARGOS (federación con su proveedor de identidad, webhook de avisos). Su caducidad la gestiona el organismo.

## Diagnóstico

1. Lista los certificados externos y su caducidad: el de la consola, el de la federación con el proveedor de identidad y el del webhook del organismo.
2. Identifica quién los emite en el organismo y su plazo de emisión.

## Acción

1. Pide el certificado nuevo con la misma identidad y el mismo uso.
2. Instálalo desde la consola o con el instalador (`argos-install`, F10-10), con un administrador de plataforma y segundo factor.
3. Reinicia solo el servicio que lo presenta.

## Verificación

- La consola presenta el certificado nuevo y el navegador no avisa.
- El inicio de sesión federado funciona.
- El webhook del organismo recibe la alerta de prueba.

## Cuándo escalar

Si la federación deja de funcionar tras la renovación: al administrador del proveedor de identidad del organismo.
