# Guía de despliegue del banco k3s de ARGOS

**Versión de la guía:** 1.1 · **Fecha:** 2026-10-08 · **Banco probado:** `banco-v0.18.2` · **Confidencialidad:** `internal`

Esta guía explica, paso a paso y con los comandos exactos, cómo se monta el banco de ARGOS sobre k3s en una máquina virtual, cómo se publica cada versión y cómo se comprueba cada capa. Está escrita a partir de lo que hicimos de verdad en `vm-argos` (Google Cloud, octubre de 2026), con los problemas que encontramos y cómo se resolvieron.

> **El banco lleva solo datos sintéticos.** No es el piloto ni una instalación para un organismo (nota de desviación ARG-002-003). En una instalación real cambian algunas cosas: dónde se guardan las claves de Vault, el TLS interno y quién hace las copias. Cada sección lo señala.

---

## 1. Cómo funciona, en una página

```
  Tu equipo                          GitHub                              VM (k3s)
  ─────────                          ──────                              ────────
  git tag banco-vX.Y.Z  ──push──▶  workflow "bench"
                                    1. construye y firma las imágenes
                                    2. las sube a GHCR (fijadas por digest)
                                    3. publica los manifiestos como
                                       artefacto OCI firmado (cosign)
                                                        ◀──cada 5 min── Flux comprueba la firma
                                                                         y aplica los manifiestos
```

- **Nadie aplica nada a mano en la VM** después de la instalación inicial. Cada cambio entra por una etiqueta `banco-vX.Y.Z` que empuja una persona (DP-21).
- **Flux solo acepta artefactos firmados** por el workflow `bench.yml` del repositorio y desde una etiqueta `banco-v…`. Cualquier otra cosa la rechaza.
- **Los secretos no están en el repositorio.** Los genera dentro del clúster el Job `secret-seeder`, y k3s los guarda cifrados en reposo.
- El banco se monta **por capas** (DP-22). La capa 1 es el núcleo y la evidencia. La capa 2, los servicios de ARGOS. La capa 3, las fuentes simuladas y la observabilidad.

### Espacios de nombres

| Espacio | Qué corre | Pod Security |
|---|---|---|
| `argos-core` | PostgreSQL, NATS, Temporal, Vault, OPA, Keycloak, almacén WORM, TSA, observabilidad | `restricted` |
| `argos-services` | API, workers, evidencia, verificador, salud | `restricted` |
| `argos-ai` | Gateway de IA (vacío en el banco: no hay GPU) | `restricted` |
| `argos-connect` | Conectores hacia las fuentes | `restricted` |
| `bench-sources` | Fuentes simuladas con datos sintéticos (no son producto) | `baseline` |

En todos, la red empieza cerrada (`default-deny`). Cada componente abre solo los flujos que necesita, en una `NetworkPolicy` junto a sus manifiestos.

---

## 2. Requisitos de la máquina

### 2.1 Lo que usamos

| Recurso | `vm-argos` |
|---|---|
| Tipo | Google Compute Engine `e2-highmem-8`, zona `us-central1-c` |
| CPU y memoria | 8 vCPU AMD EPYC, 62 GiB |
| Disco | 500 GB (unos 70 GB usados con el banco entero) |
| Sistema | Ubuntu 24.04 LTS, UEFI, vTPM 2.0 (Secure Boot desactivado) |
| GPU | ninguna: el asistente y la clasificación asistida responden 503 |

Como mínimo práctico, el banco entero pide unos **16 GiB de memoria libres y 160 GiB de disco**: los volúmenes suman 146 GiB solicitados (§9).

### 2.2 Comprobarlo (inventario de solo lectura)

Desde tu equipo, sin cambiar nada en la VM:

```bash
ssh usuario@IP_DE_LA_VM 'nproc; free -g; df -h /; lsb_release -ds; uname -r; ls /dev/tpm* 2>/dev/null; nvidia-smi 2>/dev/null || echo "sin GPU"'
```

Qué buscar: al menos 8 CPU, 32 GiB o más de memoria, 200 GB libres en `/`, Ubuntu 22.04 o 24.04 y kernel 5.15 o superior. El TPM y la GPU no son obligatorios en el banco.

### 2.3 Red

| Puerto | Para qué | Quién lo abre |
|---|---|---|
| 22/tcp | SSH de administración | el propietario de la VM |
| 80/tcp | reto HTTP-01 de Let's Encrypt | el propietario del proyecto de nube |
| 443/tcp | API y Keycloak públicos (Traefik) | el propietario del proyecto de nube |

En `vm-argos` los puertos 80 y 443 siguen cerrados en el firewall del proyecto, porque la VM la gestiona la compañía. Mientras tanto se entra por un túnel SSH (§8.3).

---

## 3. Instalación de la VM (una sola vez)

### 3.1 Clonar el repositorio en la VM

```bash
sudo apt-get install -y git
git clone https://github.com/emiliomuletdiaz1974/argos_auditoria.git
cd argos_auditoria
```

### 3.2 Ver qué va a hacer, sin hacerlo

```bash
bash platform/k8s/bench/install.sh --dry-run
```

Imprime cada orden con un `+` delante y no ejecuta ninguna.

### 3.3 Instalar

```bash
bash platform/k8s/bench/install.sh
```

Qué hace, en orden. Cada descarga se comprueba contra un SHA-256 escrito en el script antes de usarla, y nada se ejecuta mediante una tubería hacia una shell:

1. **k3s `v1.36.5+k3s1`**, con `--secrets-encryption` (los `Secret` cifrados en disco) y `--write-kubeconfig-mode 600` (solo root lee el kubeconfig).
2. **Flux CLI `2.9.6`** en `/usr/local/bin/flux`.
3. **cert-manager `v1.21.2`**. Va antes del banco porque los manifiestos declaran certificados y sus tipos tienen que existir.
4. **Kyverno `v1.19.1`**, aplicado del lado del servidor (sus CRD no caben en la anotación de un apply de cliente). Antes del banco por el mismo motivo: el banco declara la política `argos-pod-baseline`.
5. **Perfiles de seguridad en el nodo:** seccomp en `/var/lib/kubelet/seccomp/argos/` y AppArmor con `apparmor_parser`. Un pod que pide un perfil `Localhost` que no está en el nodo no arranca.
6. **Controladores de Flux** y el origen del banco (`platform/k8s/flux/`): un `OCIRepository` que vigila `oci://ghcr.io/emiliomuletdiaz1974/argos-bench` cada 5 minutos y verifica la firma, y una `Kustomization` que aplica lo verificado con `prune` y `wait`.

Volver a ejecutarlo no cambia nada de lo que ya está instalado. Así es como se reinstalan los perfiles de seguridad si cambian.

### 3.4 Comprobar la instalación

```bash
sudo k3s kubectl get nodes                      # el nodo en Ready
sudo k3s kubectl -n flux-system get pods        # controladores de Flux en Running
sudo k3s kubectl get ns --show-labels | grep pod-security   # aparece tras la primera etiqueta
```

---

## 4. Publicar una versión

### 4.1 Empujar la etiqueta

Desde tu equipo, con `main` al día y empujado:

```bash
git push origin main
git tag banco-v0.18.2
git push origin banco-v0.18.2
```

La etiqueta tiene que seguir el formato `banco-vX.Y.Z`. Cualquier otro formato lo rechaza el propio workflow.

### 4.2 Qué hace el workflow `bench`

1. **verify:** las mismas comprobaciones que el CI.
2. **Imágenes:** una por componente, en paralelo (`fail-fast: false`, así que una que falle no tira las demás). Cada imagen de infraestructura (postgres, opa, tsa, keycloak, bench-seed) se identifica por una **huella de sus archivos de entrada**: si no cambiaron, se reutiliza la imagen `inputs-<huella>` de GHCR y su pod no se recrea. Las de los servicios de ARGOS se construyen en cada etiqueta.
3. **Firma** de cada imagen con cosign (identidad OIDC de GitHub Actions, sin claves guardadas).
4. **Render:** el overlay `bench-gcp` con cada imagen fijada por digest (`tools/bench_render.py`). Flux aplica exactamente lo firmado, nunca una etiqueta que pueda moverse.
5. **Artefacto:** `flux push artifact` a GHCR y `cosign sign` del artefacto.

### 4.3 Visibilidad de los paquetes de GHCR

Flux descarga sin credenciales, así que **los paquetes de GHCR tienen que ser públicos**. La primera vez, en GitHub: *perfil → Packages → cada paquete `argos-*` → Package settings → Change visibility → Public*. En el banco, Flux respondió `DENIED` hasta que se hizo, y se recuperó solo en el siguiente reintento.

> En una instalación real con paquetes privados, Flux necesita un secreto de acceso al registro (`flux create secret oci`). El repositorio no lo trae.

### 4.4 Ver que Flux la aplicó

```bash
sudo k3s kubectl -n flux-system get ocirepository,kustomization
sudo k3s kubectl -n flux-system describe ocirepository argos-bench | grep -i "verified\|revision"
```

Lo correcto es `READY True` y la revisión `0.18.2@sha256:…`. Para no esperar al siguiente ciclo:

```bash
sudo flux reconcile source oci argos-bench -n flux-system
sudo flux reconcile kustomization argos-bench -n flux-system
```

---

## 5. Vault

Vault guarda las credenciales dinámicas de la base de datos, las claves de firma (`argos-content` y `argos-evidence`) y la PKI interna. En el banco corre en modo servidor con almacenamiento integrado (raft), nunca en modo `-dev`.

### 5.1 Inicializar (solo la primera vez)

Después de la primera etiqueta que despliega Vault (`vault-0` en marcha):

```bash
bash platform/k8s/bench/vault.sh status
bash platform/k8s/bench/vault.sh init
```

`init` muestra **una sola vez** las 5 claves de desellado (hacen falta 3 de 5 para abrir) y el token raíz. El script no las escribe en ningún archivo, variable del clúster ni log.

### 5.2 Desellar (tras `init` y después de cada reinicio del pod)

```bash
bash platform/k8s/bench/vault.sh unseal
```

Pide 3 claves, una a una, sin mostrarlas. Mientras no haya TPM, el desellado es manual: **cada vez que se reinicie `vault-0` o la VM, Vault queda sellado** y los servicios no obtienen credenciales hasta que alguien lo abre.

### 5.3 Configurar (motores, claves y políticas)

```bash
bash platform/k8s/bench/vault.sh configure
```

Pide el token raíz sin mostrarlo y ejecuta dentro del pod `vault-setup.sh`, que es idempotente:
- el almacén `argos` (kv-v2);
- la PKI raíz y la intermedia, que cert-manager usa para el mTLS interno;
- las claves de tránsito;
- el método `kubernetes`, para que cada servicio entre con su propia cuenta de servicio y nadie le entregue un token;
- las políticas de cada servicio y la del arranque.

**Hay que repetirlo cuando una versión añade políticas** antes de etiquetarla. Si no, el arranque falla con un 403 de Vault (§11.6).

### 5.4 Cómo guardar las claves

| | Banco (`vm-argos`) | Instalación real |
|---|---|---|
| Dónde | en un archivo de la VM, por decisión del responsable del banco: solo hay datos sintéticos | **nunca en la máquina**: fuera de ella y repartidas |
| Quién | la persona que administra el banco | 5 custodios distintos; cada uno guarda **una** clave en su gestor de contraseñas o en un sobre sellado en una caja fuerte |
| Token raíz | junto a las claves | revocarlo tras la configuración (`vault token revoke`) y generar uno nuevo con 3 custodios solo cuando haga falta (`vault operator generate-root`) |
| Si se pierden | se pierden los datos de Vault: hay que reinstalar el banco | ídem: **no hay recuperación** sin 3 de las 5 claves |

En el appliance, el plan es sellar Vault al TPM (F09-91). Hasta entonces, el desellado es siempre una tarea de personas.

---

## 6. Las capas, una a una

Cada capa llega con una etiqueta. Para cada una: qué se despliega, cómo comprobarlo y qué mirar si falla. Todos los comandos son de solo lectura y se ejecutan en la VM.

### 6.1 Capa 1 · núcleo y evidencia (K-03)

**Qué:** en `argos-core`, Vault, el Job `secret-seeder`, PostgreSQL 16 con AGE y pgvector, NATS JetStream, Temporal con su base, OPA (con las políticas firmadas dentro de su imagen), el almacén WORM de evidencia y una TSA de pruebas.

```bash
sudo k3s kubectl -n argos-core get pods,pvc
sudo k3s kubectl -n argos-core logs job/secret-seeder | tail -n 3      # "created" o "already there"
sudo k3s kubectl -n argos-core exec postgres-0 -c postgres -- psql -U argos -d argos -Atc "SELECT extname, extversion FROM pg_extension WHERE extname IN ('age','vector')"
bash platform/k8s/bench/vault.sh status                                  # Initialized true, Sealed false
```

**Si falla:** un pod en `Pending` casi siempre es un volumen sin disco (`kubectl describe pvc`). Si el pod se crea pero no arranca, revisa los eventos (`kubectl -n argos-core get events --sort-by=.lastTimestamp | tail`): un perfil seccomp ausente o una política de Kyverno lo dicen ahí.

### 6.2 Arranque como Jobs (K-04)

**Qué:** el Job `argos-bootstrap`. Aplica las migraciones de la base y conecta Vault con la base (credenciales dinámicas, solo la primera vez). Después crea los streams de NATS, prepara la base de Keycloak, registra las fuentes simuladas y publica el contenido normativo firmado con `argos-content`.

```bash
sudo k3s kubectl -n argos-core get jobs
sudo k3s kubectl -n argos-core logs job/argos-bootstrap | tail -n 20      # termina con "content 1.0.0 published" o "in force"
```

**Si falla:** un `403` de Vault significa que falta `vault.sh configure` con las políticas nuevas (§11.6). Para repetir el Job: `kubectl -n argos-core delete job argos-bootstrap` y `flux reconcile kustomization argos-bench`.

### 6.3 Keycloak y cuentas (K-05, K-11)

**Qué:** Keycloak 26.0.8 en modo producción, con el nombre público `id.<ip>.sslip.io`. El realm `argos` se importa una vez. El Job `keycloak-accounts` crea las cuentas del banco (`admin.test`, `manager.test`, `dpo.test`, `dpo2.test` y `auditor.test`) con contraseña temporal y TOTP obligatorio para administrador y DPO, y les asigna los roles por defecto del realm.

```bash
bash platform/k8s/bench/accounts.sh                  # contraseñas temporales, solo en esta consola
bash platform/k8s/bench/accounts.sh reset dpo.test   # otra contraseña temporal y TOTP a configurar de nuevo
```

Cada contraseña temporal sirve una vez: Keycloak pide una nueva al primer inicio de sesión, y el TOTP a quien decide. La política TOTP es **HMAC-SHA256**, así que hay que usar FreeOTP, Aegis o 2FAS. Google Authenticator y Microsoft Authenticator no la soportan.

**Si falla:** si la página de cuenta responde 401, faltan los roles por defecto (corregido en `banco-v0.18.1`). Si una cuenta dice «Account is disabled», ver §11.11.

### 6.4 Capa 2 · servicios de ARGOS (K-06)

**Qué:** en `argos-services`, la API, el worker de campañas, la evidencia (API y worker), el verificador, el servicio de salud, el planificador y la ingesta del inventario, y el worker de webhooks. Todos con postura restringida, mTLS por certificados de cert-manager emitidos por la PKI de Vault, y credenciales de base de datos dinámicas renovadas solas. Los cuatro que se suscriben a NATS con consumidor duradero usan la estrategia `Recreate`.

```bash
sudo k3s kubectl -n argos-services get pods            # todos Running y sin reinicios
sudo k3s kubectl -n argos-services get certificate     # READY True
sudo k3s kubectl -n argos-services logs deploy/challenge-worker | grep -m1 "worker ready"
```

**Si falla:** si un servicio se reinicia con «no database credentials», mira primero si Vault está sellado (§11.7) o si `postgres-0` se acaba de recrear.

### 6.5 Capa 3 · fuentes sintéticas (K-07)

**Qué:** en `bench-sources`, las fuentes simuladas (PostgreSQL, MariaDB, ficheros, LDAP y fuentes clínicas FHIR y DICOM) y los Jobs que las siembran con datos sintéticos.

```bash
sudo k3s kubectl -n bench-sources get pods,jobs
```

### 6.6 Entrada pública (K-08)

**Qué:** Traefik (el de k3s) con tres `Ingress` solo por HTTPS:
- `api.<ip>.sslip.io`, hacia la API;
- `id.<ip>.sslip.io`, hacia Keycloak, publicando solo `/realms/argos` y `/resources` y nunca el realm `master` ni la consola de administración;
- `ns.<ip>.sslip.io`, hacia el comprobador, publicando solo `/norms/` y `/verify`: el catálogo normativo, donde se abren las IRI de las obligaciones, y la comprobación de expedientes, donde lleva su QR (nota de desviación ARG-069). `ARGOS_EVIDENCE_VERIFIER_URL` de la API y del servicio de evidencia vale `https://ns.<ip>.sslip.io/verify`: es lo que va en el QR, así que tiene que ser la dirección pública del entorno.

**El día que tengamos el dominio `ns.argos.eu`:** se apunta su DNS a la IP de la VM y se añade ese nombre al `Ingress` `norms` de `platform/k8s/base/services/edge.yaml` (en `tls.hosts` y como otra regla con la misma ruta). cert-manager pide su certificado como con los demás. Desde ese momento las IRI que ya llevan los hallazgos y la evidencia firmada se abren tal cual; no hay que cambiar nada más.

El certificado lo pide cert-manager a Let's Encrypt por HTTP-01 en cuanto el puerto 80 sea alcanzable. Mientras tanto, Traefik responde con su certificado propio y el navegador avisa una vez.

```bash
sudo k3s kubectl get ingress -A
sudo k3s kubectl get certificate -A | grep -v argos-services
```

### 6.7 Seguridad del clúster (K-09)

**Qué:** la política de Kyverno `argos-pod-baseline` en `Enforce`, más los perfiles seccomp y AppArmor (§3.3, paso 5).

```bash
sudo k3s kubectl get clusterpolicy
sudo k3s kubectl get policyreport -A | head
```

### 6.8 Capa 3 · observabilidad (K-10)

**Qué:** en `argos-core`, Prometheus, Alertmanager (entrega en la consola de la API), Loki y Grafana. Nada de fuera del clúster llega a ellos.

```bash
sudo k3s kubectl -n argos-core get pods -l 'app.kubernetes.io/name in (prometheus,alertmanager,loki,grafana)'
```

---

## 7. Comprobar el banco entero

### 7.1 Desde la VM

```bash
sudo k3s kubectl get pods -A | grep -v -E "Running|Completed"    # no debería salir nada salvo la cabecera
sudo k3s kubectl -n flux-system get kustomization argos-bench    # READY True
```

### 7.2 Desde tu equipo

Con el túnel abierto (§8.3) o con el firewall abierto:

```powershell
powershell -ExecutionPolicy Bypass -File platform/k8s/bench/smoke.ps1 -User auditor.test
```

Pide la contraseña sin mostrarla, entra con la cuenta y llama a la API. Solo imprime códigos, recuentos y los datos del token que importan.

La prueba completa (campañas, evidencia, credenciales y lo que debe fallar) se hace con la colección de Postman `tools/postman/ARGOS-API-v1.postman_collection.json` y el entorno `ARGOS-banco.postman_environment.json`. Cómo fue y qué salió: [banco-k3s.md](banco-k3s.md).

---

## 8. Acceso de los equipos

### 8.1 Direcciones

| Qué | Dirección |
|---|---|
| API | `https://api.34-134-21-66.sslip.io/api/v1` |
| Keycloak (realm `argos`) | `https://id.34-134-21-66.sslip.io/realms/argos` |
| Catálogo normativo (sin cuenta) | `https://ns.34-134-21-66.sslip.io/norms/` |
| Origen permitido del front | `http://localhost:5173` |

`sslip.io` resuelve el nombre a la IP que lleva dentro, así que no hace falta comprar ni configurar un dominio.

### 8.2 Guía del front

La integración (sesión, cookie de refresco con CSRF y CORS) está en `docs/tecnica/guias/integracion-frontend.md`.

### 8.3 Túnel SSH mientras los puertos estén cerrados

1. En el archivo `hosts` de tu equipo (`C:\Windows\System32\drivers\etc\hosts` en Windows, como administrador), añade:

   ```
   127.0.0.1 api.34-134-21-66.sslip.io
   127.0.0.1 id.34-134-21-66.sslip.io
   127.0.0.1 ns.34-134-21-66.sslip.io
   ```

2. Abre el túnel y déjalo abierto mientras pruebas:
   - **En Git Bash:**

     ```bash
     bash platform/k8s/bench/tunnel.sh geographoss2000@34.134.21.66
     ```

   - **En PowerShell**, donde `bash` es el de WSL y no Git Bash:

     ```powershell
     ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:443:127.0.0.1:443 geographoss2000@34.134.21.66
     ```

3. Quita esas líneas del `hosts` el día que se abra el firewall.

---

## 9. Datos y copias de seguridad

### 9.1 Dónde viven los datos

Todos los datos persistentes están en volúmenes del aprovisionador `local-path` de k3s, en el disco de la VM, bajo `/var/lib/rancher/k3s/storage/`:

| Volumen (`argos-core`) | Tamaño | Qué guarda |
|---|---|---|
| `data-postgres-0` | 50 Gi | inventario, campañas, veredictos, hallazgos, diario, registro de seguridad |
| `data-evidence-store-0` | 50 Gi | almacén WORM: artefactos, expedientes y credenciales |
| `data-vault-0` | 5 Gi | Vault (raft): claves de firma, PKI, configuración |
| `data-temporal-db-0` | 10 Gi | historial de los workflows |
| `data-nats-0` | 10 Gi | streams de eventos |
| `data-tsa-0` | 1 Gi | sellos de tiempo de la TSA de pruebas |
| `data-prometheus-0`, `data-loki-0` | 10 Gi cada uno | métricas y logs (se pueden perder) |

### 9.2 Qué sobrevive y qué no

| Suceso | ¿Se conservan los datos? |
|---|---|
| Reinicio de un pod o una versión nueva | sí |
| Reinicio de la VM | sí (Vault queda sellado: hay que desellarlo, §5.2) |
| Borrar un `PersistentVolumeClaim` o su espacio de nombres | **no:** los volúmenes tienen la política `Delete`, la que trae por defecto `local-path`, y el directorio se borra con la reclamación |
| Pérdida o borrado del disco de la VM | **no** |

Para que borrar una reclamación por error no se lleve los datos, se puede pasar cada volumen a `Retain`, una vez y en la VM. Cada volumen queda en su sitio aunque desaparezca la reclamación, y se borra a mano:

```bash
for pv in $(sudo k3s kubectl get pv -o jsonpath='{.items[*].metadata.name}'); do
  sudo k3s kubectl patch pv "$pv" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
done
```

En el banco aún no se ha hecho.

### 9.3 Las copias de seguridad son responsabilidad del cliente

El banco **no hace copias**. La alerta `BackupRestoreTestStale` está silenciada solo en el banco por decisión del responsable. En una instalación real, la organización copia como mínimo:

1. `data-postgres-0`, con `pg_dump` o una copia en frío;
2. `data-evidence-store-0`, el almacén WORM;
3. `data-vault-0`, con `vault operator raft snapshot save`, y las claves de desellado guardadas aparte (§5.4);
4. `data-temporal-db-0` y `data-tsa-0`;
5. el secreto de cifrado de k3s, `/var/lib/rancher/k3s/server/cred/encryption-config.json`: sin él, los `Secret` de una copia del clúster no se descifran.

El procedimiento de ARGOS para copias cifradas con restauración probada está en `docs/seguridad/backup-restauracion.md` y en el runbook RB-08.

---

## 10. Operación del día a día

| Quiero… | Comando (en la VM) |
|---|---|
| ver el estado de todo | `sudo k3s kubectl get pods -A` |
| ver qué versión aplica Flux | `sudo k3s kubectl -n flux-system get ocirepository argos-bench` |
| forzar la reconciliación | `sudo flux reconcile kustomization argos-bench -n flux-system --with-source` |
| ver los logs de la API | `sudo k3s kubectl -n argos-services logs deploy/api --since=10m` |
| ver los eventos recientes | `sudo k3s kubectl get events -A --sort-by=.lastTimestamp \| tail -n 30` |
| desellar Vault tras un reinicio | `bash platform/k8s/bench/vault.sh unseal` |
| reiniciar una cuenta | `bash platform/k8s/bench/accounts.sh reset <cuenta>` |

---

## 11. Problemas que encontramos y cómo se resolvieron

### 11.1 Flux responde `DENIED` al descargar

**Causa:** los paquetes de GHCR son privados. **Solución:** hacerlos públicos (§4.3). Flux se recupera solo en su siguiente reintento.

### 11.2 El CI se pone en rojo por gitleaks con algo que no es un secreto

Gitleaks confunde con credenciales cosas como `API_HOST = "api.<ip>.sslip.io"` o las URL `http://api:8000/api/v1/…`. **Solución:** añadir la huella exacta del hallazgo a `.gitleaksignore` con su motivo en inglés. **Nunca se desactiva la regla entera.** Antes de fusionar, reproduce el CI en un clon limpio:

```bash
make lint typecheck secrets test
```

### 11.3 El workflow falla al descargar paquetes de PyPI

Es un corte de red del runner, no del código. **Solución:** en GitHub, *Actions → la ejecución → Re-run failed jobs*. Con `fail-fast: false` solo hay que relanzar lo que falló.

### 11.4 El túnel no funciona desde PowerShell

En PowerShell, `bash` es el de WSL, que no ve las claves SSH de Windows. **Solución:** la línea `ssh -N …` de §8.3 directamente en PowerShell, o `tunnel.sh` desde Git Bash.

### 11.5 Flux no aplica: `spec.strategy.rollingUpdate: Forbidden`

Pasa al cambiar a `Recreate` la estrategia de un Deployment que ya existe. El API server le puso un `rollingUpdate` por defecto, y la aplicación del lado del servidor no lo puede quitar. **Solución, una vez por Deployment** y validada antes con `--dry-run=server`:

```bash
for d in challenge-worker evidence-worker inventory-ingest webhook-worker; do
  sudo k3s kubectl -n argos-services patch deployment "$d" --type=json \
    -p '[{"op":"remove","path":"/spec/strategy/rollingUpdate"},{"op":"replace","path":"/spec/strategy/type","value":"Recreate"}]'
done
```

### 11.6 El arranque falla con un 403 de Vault

Una versión trae políticas nuevas y Vault aún no las tiene. **Solución:**

```bash
bash platform/k8s/bench/vault.sh configure
sudo k3s kubectl -n argos-core delete job argos-bootstrap
sudo flux reconcile kustomization argos-bench -n flux-system
```

Regla: **configure antes de etiquetar** una versión que cambie `vault-setup.sh`.

### 11.7 Tras un reinicio, los servicios no tienen credenciales

Vault está sellado. **Solución:** `bash platform/k8s/bench/vault.sh unseal`. En unos minutos los servicios vuelven a obtener sus credenciales.

### 11.8 Cada versión reiniciaba servicios

Tenía tres causas, ya corregidas:
- el arranque reconfiguraba la conexión de Vault con la base (ahora es idempotente);
- las imágenes de infraestructura cambiaban de digest en cada etiqueta (ahora se reutilizan por huella);
- dos pods con el mismo consumidor duradero de NATS durante la actualización (ahora con `Recreate`).

Si vuelve a pasar, mira cuál de las tres es con los logs del pod reiniciado (`kubectl logs --previous`).

### 11.9 Ninguna campaña llega a prepararse

Con «OPA is not running the signed bundle» en el log del worker: el motor compara las políticas que ejecuta OPA con el contenido firmado, y algo cargado en OPA no está en el paquete firmado. En el banco era la regla de acceso de OPA fuera del montaje `/auth` (corregido en `banco-v0.18.2`). El rechazo queda en el registro de seguridad como `content.policies_mismatch`.

### 11.10 Una verificación de subsanación no avanza

No es un fallo. Espera la aprobación del DPO en la compuerta de inicio, como cualquier campaña: la campaña queda en `pinned` y el hallazgo en `pending_verification` hasta que alguien aprueba.

### 11.11 Una cuenta dice «Account is disabled, contact your administrator»

Hay dos mensajes parecidos y no son lo mismo:

| Mensaje en Keycloak | Qué pasa | Qué hacer |
|---|---|---|
| «Account is temporarily disabled…» | Cinco contraseñas fallidas seguidas: bloqueo temporal (60 s que crecen hasta 15 min). | Esperar, o desbloquear abajo. |
| «Account is disabled…» | La cuenta tiene `enabled: false` y no vuelve sola. | Habilitarla abajo. |

En el banco (2026-10-08) `manager.test` pasó del primero al segundo: se reinició con `accounts.sh reset` mientras estaba bloqueada. Keycloak muestra una cuenta bloqueada como `enabled: false`, y el Job reescribía la cuenta entera, así que el bloqueo temporal se quedó guardado como deshabilitación. Desde `banco-v0.18.3`, el reinicio solo escribe las acciones obligatorias y además desbloquea y habilita la cuenta: `accounts.sh reset <cuenta>` lo arregla todo de una vez.

**Comprobar** (desde la VM; no muestra ninguna contraseña):

```bash
sudo k3s kubectl -n argos-core exec deploy/keycloak -- sh -c 'K=/opt/keycloak/bin/kcadm.sh; C="--config /tmp/kcadm.config"; $K config credentials $C --server http://localhost:8080 --realm master --user admin --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" && $K get users $C -r argos -q username=manager.test -q exact=true --fields username,enabled; rm -f /tmp/kcadm.config'
```

**Arreglar con la versión corregida desplegada:**

```bash
bash platform/k8s/bench/accounts.sh reset manager.test
```

Da otra contraseña temporal (y pide el TOTP de nuevo a quien lo tenga). **Si solo se quiere habilitar la cuenta, sin cambiarle la contraseña**, o la versión desplegada es anterior a `banco-v0.18.3`:

```bash
sudo k3s kubectl -n argos-core exec deploy/keycloak -- sh -c 'K=/opt/keycloak/bin/kcadm.sh; C="--config /tmp/kcadm.config"; $K config credentials $C --server http://localhost:8080 --realm master --user admin --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" && ID=$($K get users $C -r argos -q username=manager.test -q exact=true --fields id --format csv --noquotes) && $K delete attack-detection/brute-force/users/$ID $C -r argos && $K update users/$ID $C -r argos -s enabled=true; rm -f /tmp/kcadm.config'
```

También se puede desde la consola de administración de Keycloak (`https://id.<ip>.sslip.io/admin`, realm `master`, usuario `admin`): realm `argos` → Users → la cuenta → interruptor **Enabled**.

**Para que no vuelva a pasar:** no reiniciar una cuenta a ciegas mientras alguien sigue probando contraseñas; si el bloqueo es solo temporal, esperar 15 minutos basta.

---

## 12. Pendiente para pasar de banco a instalación real

- TLS en Vault y OPA, para que ARGOS corra en `production` y no en `staging`.
- Abrir los puertos 80 y 443, o usar un dominio propio, para el certificado real y un DID de la evidencia resoluble desde fuera.
- Claves de Vault fuera de la máquina y repartidas (§5.4), y más adelante selladas al TPM.
- Volúmenes con `Retain` (§9.2) y copias hechas por la organización (§9.3).
- GPU para la capa de IA, y la imagen endurecida del appliance (F1-11a, F09-90, F09-91).
