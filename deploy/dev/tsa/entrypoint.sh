#!/bin/sh
# Creates the test CA and the TSA certificate on first start. The keys live in the container's
# volume, never in the repository; dropping the volume makes a new CA.
set -eu
DATA=/data
mkdir -p "$DATA"

if [ ! -f "$DATA/tsa.pem" ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout "$DATA/ca.key" -out "$DATA/ca.pem" -days 3650 \
    -subj "/O=ARGOS development/CN=ARGOS development TSA root (not qualified)" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout "$DATA/tsa.key" -out "$DATA/tsa.csr" \
    -subj "/O=ARGOS development/CN=ARGOS development TSA (not qualified)"
  printf 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=critical,timeStamping\n' > "$DATA/tsa.ext"
  openssl x509 -req -in "$DATA/tsa.csr" -CA "$DATA/ca.pem" -CAkey "$DATA/ca.key" \
    -CAcreateserial -out "$DATA/tsa.pem" -days 1825 -extfile "$DATA/tsa.ext"
  echo 01 > "$DATA/serial"
fi

exec python /tsa/server.py
