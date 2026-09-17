# Access: are the identities reaching a data category limited to the authorized profiles?
#
# input:
#   target      string  probed object, e.g. "his.episodes"
#   category    string  classification of the object, e.g. "special_category.health"
#   identities  array   [{"name": string, "profile": string | null}], a missing profile counts as null
# data.client (approved at deployment):
#   authorized_profiles[category]  array of profile names
package argos.access

default authorized_profiles := []

authorized_profiles := data.client.authorized_profiles[input.category]

unauthorized contains identity.name if {
	some identity in input.identities
	not object.get(identity, "profile", null) in authorized_profiles
}

default compliant := false

compliant if count(unauthorized) == 0

verdict := {
	"compliant": compliant,
	"unauthorized": sort(unauthorized),
	"total": count(input.identities),
	"rule": "argos.access",
}
