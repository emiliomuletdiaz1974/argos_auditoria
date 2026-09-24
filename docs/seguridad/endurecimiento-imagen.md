# Endurecimiento de la imagen y sellado del disco

**Versión:** 1.0 · **Fecha:** 2026-09-24 · **Componentes:** ARG-081, ARG-082 (F09-14) · **Confidencialidad:** `client`

Todo lo que la imagen del appliance necesita está escrito y probado sin hardware. Las tareas `F09-90` (imagen real y puntuación CIS) y `F09-91` (Secure Boot, arranque medido y LUKS sellado al TPM) solo tienen que ejecutarlo sobre el equipo.

## Endurecimiento CIS (ARG-081)

**Referencia:** CIS Ubuntu Linux 24.04 LTS, perfil Level 1 Server. Es la referencia contractual, la que conoce el auditor del cliente.

- **`platform/image/harden.sh`:** idempotente y por secciones del benchmark.
  - **1.1.1** Módulos de sistemas de ficheros que no se usan: cramfs, freevxfs, hfs, hfsplus, jffs2 y udf.
  - **1.1.2** `/dev/shm` y `/tmp` en tmpfs con `nodev`, `nosuid` y `noexec`.
  - **1.5** Sin volcados de memoria de programas setuid.
  - **1.7** Aviso de acceso.
  - **3.3** Parámetros de red y de núcleo.
  - **4.1** auditd, con las reglas versionadas en `platform/image/audit/argos.rules`. Cubre cambios en `/etc` y sudoers, las claves de ARGOS, ejecuciones como root, montajes, módulos del núcleo, cambios de hora y sesiones, y deja las reglas inmutables hasta el siguiente arranque.
  - **5.1** SSH solo con llave, por el bastión del cliente y el grupo `argos-ops`.
  - **5.4** Política de contraseñas de las cuentas locales.
  - **2.x** Retirada de paquetes que no se usan.
- **Idempotencia:** cada fichero se escribe solo si cambia su contenido y cada línea solo si falta. Una segunda ejecución no toca nada, ni el contenido, ni los permisos, ni la fecha.
- **Sin silencios:** lo que necesita núcleo o repositorio (cargar sysctl y las reglas de auditoría, instalar auditd) es un error al construir la imagen. Solo en la prueba en contenedor se salta, y con una línea `SKIP` que dice por qué.

### Excepciones

Están en `platform/image/hardening-exceptions.yaml`. Cada una lleva la comprobación, su justificación y quién la acepta; sin cualquiera de las tres, la puerta rechaza el fichero.

| Comprobación | Por qué no se cumple |
|---|---|
| 3.3.1 · reenvío IP desactivado | k3s enruta el tráfico de los pods; las políticas de red y el mTLS interno deciden quién habla con quién |
| 1.1.1.10 · `usb-storage` no disponible | El appliance aislado solo recibe y entrega en soporte extraíble, por la esclusa (ARG-090) |

### Puerta de puntuación

`tools/cis_gate.py` lee el informe del escáner de la imagen y las excepciones, y rechaza la imagen en dos casos:

- la puntuación es menor del 90 % del perfil: aprobadas entre aprobadas y fallidas, sin contar las que no aplican;
- hay un fallo que nadie aceptó por escrito.

Las excepciones no suben la puntuación. El job `hardening-gate` del CI está declarado y reservado hasta que exista la imagen (`F09-90`).

## Arranque medido y disco sellado (ARG-082)

- **`platform/image/seal-disk.sh`** (enrolamiento de fábrica):
  1. comprueba Secure Boot y no toca nada si está desactivado;
  2. genera la clave de recuperación, la imprime una vez para el sobre del cliente y no la guarda en ningún fichero;
  3. sella el volumen `argos-data` al TPM con los PCR 7 (estado de Secure Boot) y 11 (el kernel unificado);
  4. deja `/etc/crypttab` para que el volumen se abra con el TPM al arrancar.
- **`platform/image/reseal-after-update.sh`** (actualización del kernel, con dos sellos a la vez):
  - `prepare`, antes de reiniciar: apunta qué slot del TPM tiene el sello que funciona hoy;
  - `confirm`, tras un arranque sano con la entrada esperada: sella a los PCR nuevos y solo después retira el slot apuntado.

  El sello viejo nunca desaparece antes de que exista el nuevo.

## Cómo se prueba

- **`tests/tools/test_cis_gate.py`:**
  - el 89 % no pasa;
  - el 91 % con un fallo sin aceptar no pasa;
  - el 91 % con sus fallos aceptados pasa;
  - una excepción sin justificación o sin responsable es un error.
- **`tests/platform/test_harden_idempotent.py`:**
  - dos ejecuciones en `ubuntu:24.04` sin red ni capacidades, y la segunda no cambia ningún fichero de `/etc`;
  - la configuración queda como se espera;
  - los saltos se anuncian;
  - sin permiso para saltar, la ejecución falla.
- **`tests/platform/test_seal_scripts.py`**, con stubs de `mokutil`, `systemd-cryptenroll` y `bootctl`:
  - los scripts pasan `bash -n`;
  - el sellado aborta sin Secure Boot;
  - la clave de recuperación no queda en ningún fichero;
  - el resellado rechaza un arranque inesperado y retira el sello viejo solo después de crear el nuevo.

## Límites

- **Numeración de las excepciones:** hay que contrastarla con la versión del benchmark que use el escáner de `F09-90`.
- **El primer arranque con un kernel nuevo** necesita que el sello nuevo pueda abrirse con los PCR que aún no se han medido. Se validará en el hardware (`F09-91`), con la política de PCR firmada del kernel unificado o con la clave de recuperación como último recurso.
