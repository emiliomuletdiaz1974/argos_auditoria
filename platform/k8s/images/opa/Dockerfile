# K-03 · OPA of the bench with the operational rules of the library inside (ARG-036): the challenge
# engine compares what OPA runs with the signed content bundle (SEC-011), so the policies travel in
# this signed image and never in a mount. The hashes of the tokens are not here: the pod computes
# them at start from its generated secret.
FROM openpolicyagent/opa:1.20.2@sha256:7b15f9d96345dfa639322ad97f65a0b38260f95efcdd7f5c24e284228708f06c
COPY library/policies /policies
COPY deploy/dev/opa/client /data
# Under /auth, as in development: the engine leaves that mount out of the comparison (K-99).
COPY deploy/dev/opa-auth/authz.rego /auth/authz.rego
