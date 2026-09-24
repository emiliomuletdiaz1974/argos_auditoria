# ADR-0015 · Operación y despliegue sin appliance: qué se construye ya y qué espera al hardware

- **Estado:** Aceptado
- **Fecha:** 2026-09-24
- **Decide:** el usuario (tarea F10-00) · **Aprobado:** 2026-09-24
- **Contexto:** Fase 10 · Operación y despliegue (ARG-091…ARG-100) · Pliego P-24, P-26, P-27, P-28 y P-29 · Plan Director §8.2 «Fase 10» y «Piloto», §7.2.7 · Especificación Técnica §3.9, §3.10 y §6

## Contexto

El documento de la Fase 10 describe la operación sobre el appliance real: Prometheus y Loki en k3s, un instalador que configura la red y sella el disco, la comprobación de la sala con IPMI, alta disponibilidad con dos o tres nodos y una campaña de autoverificación contra un banco de pruebas. No hay hardware (F1-11a y F1-11b siguen esperando) y todo corre en Docker Compose, como en la Fase 09 (ADR-0014).

Lo que hay en el repositorio al empezar:

- **Observabilidad del compose:**
  - Prometheus con las reglas del registro de seguridad y del backup, que solo recoge las métricas de la API;
  - Grafana sin paneles;
  - Loki sin nada que le envíe logs;
  - ningún Alertmanager.
- **Métricas del dominio:** solo el registro de seguridad y la última prueba de restauración (en `/metrics` de la API). No hay métricas del diario, del WORM, de las colas, de las compuertas ni de los cortacircuitos.
- **Logs:** los servicios ya escriben JSON con los campos obligatorios y admiten `journal_seq` (F1-02).
- **Etapa `selfcheck` del CI:** declarada y vacía desde F1-10. No existe ningún reto cuyo objetivo sea el propio ARGOS ni un conector que apunte al appliance.
- **Alta de sistemas:** los sistemas se dan de alta con `tools/register_dev_sources.py`; no hay ruta de la API para hacerlo, y por tanto ningún sitio donde aplicar un límite de talla.
- **Uso de la IA:** el gateway guarda cada uso en `argos.ai_usage` (tokens de entrada y salida), base de la dimensión de tokens por día.

## Decisión

1. **Tres niveles, como ADR-0014, declarados por tarea.**
   - **Se construye y se prueba ya en el compose:** el servicio de salud del dominio, las reglas con Alertmanager, los paneles aprovisionados, Loki alimentado por los propios servicios, los runbooks enlazados desde las alertas, los límites de talla, la autoverificación de release, el instalador y la conmutación asistida de la talla M (con dos PostgreSQL en contenedores).
   - **Se escribe y se valida sin hardware:** la comprobación de sala, con los analizadores probados sobre salidas reales capturadas de `ipmitool`, `ethtool`, `ping` y `nvidia-smi`, y los pasos del instalador que tocan la red o el disco, probados con dobles.
   - **Espera al appliance (MANUAL):** la instalación completa desde cero, la comprobación de sala medida, la HA en dos nodos reales y el quórum de la talla L.
2. **Un servicio de salud del dominio** (`services/health`, paquete `argos_health`), no un sidecar por servicio.
   - **Métricas en `/metrics`:**
     - verificación rotativa del diario (el último tramo cada 5 minutos, entero cada 24 horas);
     - canario del WORM, que escribe y relee cada 30 segundos en un espacio de trabajo;
     - campañas y horas en compuerta;
     - cortacircuitos abiertos;
     - colas de sellado, webhooks y revisión;
     - ocupación del volumen de evidencia;
     - caducidad de los certificados internos;
     - marcas de tiempo de los trabajos.
   - **Datos para la autoverificación** en `/facts`: los mismos hechos, en JSON.
   - **Identidad:** su propio rol de base de datos de solo lectura, con credenciales dinámicas, y mTLS.
3. **Reglas desde la especificación.** Cada objetivo medible del documento técnico es una fila de una tabla: objetivo → métrica → umbral → runbook. La tabla vive en el repositorio y se prueba con `promtool test rules`. Nombres de alerta en inglés (ADR-0005); resúmenes en castellano. Alertmanager entrega siempre a la consola y, si el organismo lo configura, a su webhook; nada sale del appliance salvo eso.
4. **Loki sin recolector: cada servicio envía sus logs por HTTP** (opción B de F10-00). Un manejador de `argos_common.logs` manda por lotes a la API de ingesta de Loki los mismos registros JSON que ya escribe en la salida estándar. Tiene una cola acotada, y si Loki no responde descarta y cuenta lo descartado: nunca bloquea al servicio. Sin `ARGOS_LOKI_URL` no envía nada. Así ningún contenedor necesita el socket de Docker y la postura de F09-03 no tiene excepciones. El mismo mecanismo vale en el appliance, donde no hace falta un recolector por nodo para los servicios de ARGOS. Solo dos etiquetas (servicio y nivel) para contener la cardinalidad. Los eventos que también son asientos llevan `journal_seq`, y Grafana enlaza del log al asiento.
5. **Los runbooks son parte del producto.**
   - **Dónde viven:** `docs/operacion/runbooks/RB-01…RB-12.md`, con la estructura síntoma → diagnóstico → acción → verificación → cuándo escalar.
   - **Enlace:** cada alerta lleva `runbook_url`, y la consola muestra el runbook de la alerta activa.
   - **Prueba:** un test exige que toda alerta tenga su runbook y todo runbook su alerta o su procedimiento.
   - **Simulacro:** una herramienta sortea dos runbooks, cronometra el simulacro y lo deja en el diario.
6. **Límites de talla honestos.**
   - **Perfiles:** S, M y L en configuración versionada (sistemas, activos inventariables, campañas en paralelo y tokens de IA por día).
   - **Franjas:** verde, ámbar al 80 % y rojo al 100 %.
   - **Rechazo:** con el mensaje del documento, en la nueva ruta `POST /api/v1/systems` y en el arranque de una campaña.
   - **Serie local:** 13 meses en `argos.capacity_snapshots`, sin salir del appliance.
7. **ARGOS verifica ARGOS** con el mismo motor, la misma DSL y la misma evidencia.
   - **Retos `self-*`:** usan los conectores que ya existen, apuntando al propio appliance con una cuenta de solo lectura. El conector SQL lee la base con un rol `svc_selfcheck`, y el conector REST lee los `/facts` del servicio de salud. No hay conector nuevo.
   - **El reto trampa `self-099`** siempre falla. Si su hallazgo no aparece en el expediente, la release se bloquea.
   - **`tools/selfcheck.py`:** lanza la campaña, espera el sello y exige cero hallazgos graves y la trampa presente, y adjunta el expediente a la release.
   - **En desarrollo** corre con `make selfcheck` contra el compose.
   - **En el CI** va en un runner propio, porque necesita el entorno entero. Mientras no exista ese runner, el job queda declarado y `make selfcheck` es la puerta local de cada release.
8. **Alta disponibilidad por tallas sin teatro.**
   - **Talla M:** conmutación asistida (`platform/ha/size-m/failover.sh`, `rejoin.sh`), con simulacro por defecto y `--confirm` para ejecutar, y sin failover automático. Se prueba con dos PostgreSQL en replicación física dentro de un perfil `ha` del compose, incluida la verificación del diario tras promover.
   - **Talla L:** con quórum (Patroni y etcd de k3s), se escribe y espera a tener tres nodos.
9. **El instalador de la semana 1** es una CLI guiada (`services/installer`, paquete `argos_installer`, orden `argos-install`), no una TUI con dependencias gráficas.
   - **Pasos:** cada uno con ejecutar y verificar, ejecución en seco y reanudación desde el paso que falló.
   - **Informe:** firmado con la clave de release de Vault transit, asentado en el diario y exportable por la esclusa (F09-13).
   - **Hardware:** los pasos que tocan la red y el disco llaman a los scripts de F09-14 y se prueban con dobles.
10. **Piloto:** seis tareas MANUAL (`P-01…P-06`), una por semana de implantación (Especificación §6), cada una con la lista de materiales que el equipo prepara de antemano.

## Consecuencias

- **Operación completa en desarrollo:** la fase deja la operación entera probada en el compose. Una release del compose se publica ya con su expediente de autoverificación.
- **Lo que llega con el hardware:** el paso al appliance cambia el orquestador (ya escrito tras un puerto en F09-10), y la HA real. Nada más.
- **Logs:** llegan a Loki solo los de los servicios de ARGOS; los de las piezas de terceros (PostgreSQL, Keycloak, Vault, NATS, Temporal) siguen en `docker compose logs` y en el paquete de diagnóstico. Un corte de Loki pierde logs, nunca servicio, y la pérdida queda contada en una métrica.
- **Sin CI completo todavía:** la puerta del CI depende de un runner propio. Hasta que exista, la autoverificación la ejecuta quien publica la release.

## Alternativas descartadas

- **Un recolector que lea el socket de Docker en desarrollo** (propuesto en la primera versión de este ADR). El usuario lo descartó en F10-00: sería la única excepción a la postura de contenedores de F09-03, y el socket da el control del anfitrión.

- **Esperar al hardware para toda la fase.** Dejaría sin hacer la parte que no depende de él y retrasaría la autoverificación, que da sentido al resto.
- **Un exporter por servicio.** Multiplica los procesos y reparte la misma consulta; el documento de fase también elige un punto único.
- **Un conector `self.k8s` nuevo.** Duplicaría lo que los conectores SQL y REST ya hacen de solo lectura. La postura de los pods se leerá de la API de Kubernetes cuando haya k3s (F10-92).
- **Failover automático en la talla M.** Un «split-brain» en un almacén de evidencia sería peor que diez minutos de conmutación con decisión humana; el documento de fase ya lo descarta.
