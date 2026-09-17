# Retention: does the measured age of the records fit the client's approved retention schedule?
#
# input:
#   category               string  classification of the probed data, e.g. "special_category.health"
#   treatment              string  record of processing activities id, e.g. "HIS-episodes"
#   max_age_days           number  age of the oldest record, measured by the probe
#   out_of_term            number  records older than the applied term
#   documented_exceptions  number  of those, records with a documented legal hold
# data.client (approved at deployment):
#   retention_schedule[treatment].days   term declared for a treatment
#   retention_defaults[category].days    fallback term per category
package argos.retention

default term_days := 0

term_days := data.client.retention_schedule[input.treatment].days

term_days := data.client.retention_defaults[input.category].days if {
	not data.client.retention_schedule[input.treatment]
}

default compliant := false

compliant if {
	term_days > 0
	input.max_age_days <= term_days
}

# Legitimate exceptions: records past the term, but every one of them documented.
compliant if {
	term_days > 0
	input.out_of_term > 0
	input.out_of_term == input.documented_exceptions
}

verdict := {
	"compliant": compliant,
	"applied_term_days": term_days,
	"rule": "argos.retention",
}
