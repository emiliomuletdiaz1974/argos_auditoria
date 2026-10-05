# K-05 · Keycloak of the bench, built once for PostgreSQL and its health checks. In production mode
# Keycloak builds its configuration at start unless the image already carries it, and that would
# write inside the image: the pod runs with a read-only root and starts with --optimized.
FROM quay.io/keycloak/keycloak:26.0.8@sha256:09a381c715ab0b111835b70f2905955274843a219c6f27efb348e4d9f4086858
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true
RUN /opt/keycloak/bin/kc.sh build
