# Manifiestos de k3s

ARGOS en producción corre sobre k3s (ARG-003). Esta carpeta guarda sus manifiestos con kustomize.

| Carpeta | Qué contiene |
|---|---|
| `base/` | Lo que tiene todo clúster de ARGOS: los espacios de nombres y una red denegada por defecto |
| `overlays/bench-gcp/` | El banco en la VM de Google Cloud (DP-20): **solo datos sintéticos** |
| `security/` | Kyverno, cert-manager, seccomp y AppArmor (F09-92, ADR-0014); se aplican en K-09 |
| `base/core/` | Capa 1 del banco (K-03): Vault en modo servidor, el Job que genera los secretos y PostgreSQL con AGE y pgvector |
| `bench/vault.sh` | Inicializar y desellar Vault: las claves solo salen en la consola de quien lo ejecuta |
| `bench/install.sh` | Instalación única de la VM: k3s y Flux, con versión y SHA-256 fijados (K-02F) |
| `flux/` | De dónde saca Flux el banco (el artefacto firmado de GHCR) y cómo lo aplica |

## Espacios de nombres

| Espacio | Qué corre | Pod Security |
|---|---|---|
| `argos-core` | PostgreSQL, NATS, Temporal, Vault, OPA, Keycloak | `restricted` |
| `argos-services` | API, workers, evidencia, verificador, salud | `restricted` |
| `argos-ai` | Gateway de IA (y el modelo local cuando haya GPU) | `restricted` |
| `argos-connect` | Conectores hacia las fuentes | `restricted` |
| `bench-sources` | Fuentes simuladas del banco, que no son producto | `baseline` |

En todos, la red empieza cerrada (`base/default-deny.yaml`): nada entra y lo único que sale es la consulta al DNS del clúster. Cada componente abre, junto a sus manifiestos, solo los flujos que necesita.

## Reglas

- **Ningún secreto en el repositorio.** Las contraseñas y tokens los genera dentro del clúster el Job `secret-seeder` (`base/core/seeder/`): crea con valores aleatorios los que faltan en `secrets.yaml` y nunca cambia uno que exista. k3s los guarda cifrados en reposo (`--secrets-encryption`). `tests/security/test_k8s_bench.py` falla si aparece un `Secret` o algo con forma de credencial.
- **Se despliega desde una etiqueta (DP-21).** Una persona empuja `banco-vX.Y.Z`. El workflow `.github/workflows/bench.yml` construye y firma las imágenes, y publica este overlay, con cada imagen fijada por digest, como artefacto OCI firmado en GHCR. Flux, en la VM, comprueba la firma y lo aplica. Nada se aplica a mano después de la instalación inicial.

Instalar la VM, una sola vez y desde un clon del repositorio en ella:

```bash
bash platform/k8s/bench/install.sh --dry-run
bash platform/k8s/bench/install.sh
```

Vault arranca sellado y sin inicializar. La primera vez, y después de cada reinicio de su pod, lo desella una persona en la VM:

```bash
bash platform/k8s/bench/vault.sh init     # solo la primera vez: guarda las claves fuera de la VM
bash platform/k8s/bench/vault.sh unseal   # 3 de las 5 claves
```

Después, cada despliegue es una etiqueta:

```bash
git tag banco-v0.1.0 && git push origin banco-v0.1.0
```

Comprobar que el overlay se construye:

```bash
kubectl kustomize platform/k8s/overlays/bench-gcp
```
