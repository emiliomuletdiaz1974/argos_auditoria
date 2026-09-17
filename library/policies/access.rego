# Access: are the identities reaching a data category limited to the authorized profiles?
#
# input:
#   target      string  probed object, e.g. "his.episodes"
#   category    string  classification of the object, e.g. "special_category.health"
#   identities  array   [{"name": string, "profile": string | null}], a missing profile counts as null
#   result      object  what the probe brought back; its `rows[].role_name` are identities too, and
#                       their profile is the one the client declared in identity_profiles
# data.client (approved at deployment):
#   authorized_profiles[category]  array of profile names
#   identity_profiles[name]        profile of an identity of the probed system
package argos.access

default authorized_profiles := []

authorized_profiles := data.client.authorized_profiles[input.category]

declared_identities := object.get(input, "identities", [])

probed_identities := [identity |
	some row in object.get(input, ["result", "rows"], [])
	name := object.get(row, "role_name", null)
	name != null
	identity := {"name": name, "profile": object.get(data.client.identity_profiles, name, null)}
]

identities := array.concat(declared_identities, probed_identities)

unauthorized contains identity.name if {
	some identity in identities
	not object.get(identity, "profile", null) in authorized_profiles
}

default compliant := false

# Without a single identity there is no evidence to absolve with: the probe brought nothing.
compliant if {
	count(identities) > 0
	count(unauthorized) == 0
}

verdict := {
	"compliant": compliant,
	"unauthorized": sort(unauthorized),
	"total": count(identities),
	"rule": "argos.access",
}
