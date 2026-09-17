# ADR-0009 · Modelo local y servidor de inferencia en desarrollo

- **Estado:** Aceptado
- **Fecha:** 2026-09-17
- **Decide:** el usuario (tarea F06-00) · **Aprobado:** 2026-09-17
- **Contexto:** Fase 06 · IA local (ARG-051…060) · Pliego P-03 · Especificación Técnica §3.5 y §5

> El plan de la Fase 06 pedía este ADR con el número 0006, que ya está ocupado por la pila de la ontología. Se numera 0009.

## Contexto

La Fase 06 mete el asistente dentro del perímetro: sin una sola llamada al exterior (P-03). En el appliance eso es vLLM sirviendo un modelo de pesos abiertos cuantizado en la GPU, con una API compatible OpenAI a la que solo llega el gateway.

En desarrollo no hay Servidor Cognitivo: el pendiente de hardware (F1-11) sigue abierto desde el 2026-09-16. Hay que poder construir y probar los diez componentes de la fase sin GPU, y que lo construido valga tal cual cuando llegue la máquina.

Tres cosas hay que decidir: qué modelo, con qué servidor en desarrollo, y cómo se sustituye en el appliance sin tocar código.

## Decisión

**1. El modelo es configuración, no código.** Ningún módulo nombra un modelo. El gateway habla con una API compatible OpenAI cuya dirección y nombre de modelo servido vienen de la configuración tipada (`ARGOS_LLM_BASE_URL`, `ARGOS_LLM_MODEL`). Cambiar de modelo es una actualización de contenido —los pesos viajan como contenido con su hash en el manifiesto firmado (ARG-040)—, nunca una release.

**2. Modelo de referencia: Qwen2.5-14B-Instruct, licencia Apache 2.0**, cuantizado AWQ a 4 bits para el appliance de talla M. Razones: pesos abiertos con licencia permisiva que admite uso comercial sin cláusulas de usuario activo; multilingüe con castellano sólido, que es la lengua del corpus normativo; tamaño que cabe holgado en la talla S y deja contexto y concurrencia en la M; y soporte de `guided_json` en vLLM, que es lo que el contrato `chat_json` necesita.

Para embeddings, **`intfloat/multilingual-e5-small`** (MIT): compacto, multilingüe y suficiente para decenas de miles de fragmentos sobre pgvector con índice HNSW.

**3. En desarrollo, el servidor es llama.cpp a través de su servidor compatible OpenAI**, con el mismo modelo en cuantización GGUF Q4_K_M sobre CPU. Corre en el `compose` de desarrollo como un servicio más, responde en el mismo `/v1/chat/completions` y se sustituye por vLLM en el appliance cambiando la configuración. Lo que no ofrece en CPU es velocidad: el objetivo de primer token por debajo de 2 s se mide en la GPU real (F06-98), no aquí.

**4. Los tests no dependen del modelo.** Todo componente de la fase se prueba contra un **backend simulado y determinista** que implementa la misma API: dada una entrada, devuelve una salida fijada en un fichero. Los tests de la fase, incluidos los de CI, corren sin pesos y sin GPU. Los conjuntos dorados (ARG-059) se ejecutan contra el modelo real y son una puerta de release, no de cada `make check`.

**5. Los pesos no entran en el repositorio ni se descargan solos.** La descarga la hace una persona (tarea manual), con la licencia a la vista, al volumen de datos del entorno de desarrollo, que está en `.gitignore`. El hash de lo descargado se anota para poder compararlo con el del manifiesto.

## Consecuencias

- La fase se puede construir entera antes de que llegue el hardware, y lo construido no cambia cuando llegue: solo la configuración.
- El coste es que en desarrollo la inferencia real es lenta. Se asume: la velocidad es un requisito del appliance, y se mide allí.
- Si la licencia del modelo de referencia cambiara, se sustituye sin tocar código; la decisión que hay que rehacer es esta, no la arquitectura.
- El backend simulado es producto, no andamiaje de un test: vive en el repositorio con sus casos, porque es lo que permite que el CI sea reproducible.

## Alternativas descartadas

- **Ollama** en desarrollo: cómodo, pero añade su propio formato de modelos y su propia API por encima de la compatible, y lo que se prueba deja de parecerse a lo que corre en el appliance.
- **Un modelo más pequeño en desarrollo (1-3B)** y otro en producción: dos comportamientos distintos, y los conjuntos dorados dejarían de significar nada.
- **Llamar a un proveedor externo en desarrollo**: rompe P-03 aunque sea «solo en desarrollo», y acostumbra al código a una dependencia que el producto no puede tener.
