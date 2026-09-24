FROM apache/age:release_PG16_1.5.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-pgvector \
 && rm -rf /var/lib/apt/lists/*
COPY init/ /docker-entrypoint-initdb.d/
# ARG-083 (F09-06): installs the certificate of cert-issuer for the server and reloads it on renewal
COPY --chmod=0755 tls-entrypoint.sh /usr/local/bin/tls-entrypoint.sh
ENTRYPOINT ["tls-entrypoint.sh"]
