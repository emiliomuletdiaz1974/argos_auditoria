# ARG-065 · Development time stamping authority (deviation note ARG-064-065).
# RFC 3161 served by `openssl ts`, with its own test CA. Its stamps are not qualified.
FROM python:3.12-alpine
RUN apk add --no-cache openssl
COPY openssl.cnf server.py entrypoint.sh /tsa/
EXPOSE 3180
ENTRYPOINT ["sh", "/tsa/entrypoint.sh"]
