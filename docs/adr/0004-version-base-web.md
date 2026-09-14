# ADR-0004 · Versión base de la web comercial

**Estado:** Propuesta · **Fecha:** 2026-09-14

## Contexto
El informe de traspaso y el Plan Director fijan v6 como versión de referencia y exigen incorporar el aviso legal (LSSI-CE art. 10) y la política de privacidad (RGPD art. 13) de v7 antes de difundir la URL. En la carpeta de trabajo solo están desempaquetadas v4 y v7_1; v6 y v7 están dentro del ZIP de la base de conocimiento. Los seis PHP son idénticos en v4, v6, v7 y v7_1: la diferencia está solo en `index.html` y los ficheros de SEO (favicon, og, robots, sitemap, preguntas-frecuentes).

## Decisión (recomendada)
Partir de **v7_1**: incluye el bloque legal obligatorio y las mejoras P1–P3 ya probadas. Portar a mano el bloque legal a v6 dentro de un `index.html` de ~300 KB es trabajo con riesgo de error y sin beneficio para el backend.

## Consecuencias
- Se publica también `preguntas-frecuentes.html`, sectores clicables y el botón de WhatsApp. Si producto no quiere alguno, se retira en una tarea de frontend aparte.
- Hay que revisar que la política de privacidad de v7_1 menciona los plazos de conservación que fije W-07.

## Alternativas descartadas
- v6 + bloque legal portado (lo que dice el Plan Director): respeta la decisión de producto, pero añade un porte manual del HTML legal.
