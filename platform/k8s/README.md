# Manifiestos de k3s

ARGOS en producción corre sobre k3s (ARG-003). Esta carpeta guarda sus manifiestos con kustomize.

| Carpeta | Qué contiene |
|---|---|
| `base/` | Lo que tiene todo clúster de ARGOS: los espacios de nombres y una red denegada por defecto |
| `overlays/bench-gcp/` | El banco en la VM de Google Cloud (DP-20): **solo datos sintéticos** |
| `security/` | Kyverno, cert-manager, seccomp y AppArmor (F09-92, ADR-0014); se aplican en K-09 |

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

- **Ningún secreto en el repositorio.** Las contraseñas, tokens y claves se generan dentro del clúster al arrancar (K-04). `tests/security/test_k8s_bench.py` falla si aparece un `Secret` o algo con forma de credencial.
- **Lo despliega una persona.** Estos manifiestos se aplican en la VM siguiendo las tareas MANUAL de la etapa K.

Comprobar que el overlay se construye:

```bash
kubectl kustomize platform/k8s/overlays/bench-gcp
```
