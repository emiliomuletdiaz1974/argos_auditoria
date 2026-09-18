# OPA's own authorization (--authentication=token --authorization=basic).
#
# OPA decides verdicts of the challenge engine, so who may talk to it is part of the product:
# - without a token, only the liveness endpoint answers;
# - with a known token, a client may only evaluate an argos.* package;
# - nobody may load, replace or read policies, nor read data outside argos.* over the API:
#   policies come from the read-only mount of the library.
#
# Tokens are compared by their SHA-256 (clients.json), so the data OPA holds reveals none.
package system.authz

import rego.v1

default allow := false

allow if {
	input.method == "GET"
	input.path == ["health"]
}

allow if {
	input.method == "POST"
	input.path[0] == "v1"
	input.path[1] == "data"
	input.path[2] == "argos"
	known_client
}

known_client if {
	input.identity
	crypto.sha256(input.identity) in object.keys(data.opa_clients)
}
