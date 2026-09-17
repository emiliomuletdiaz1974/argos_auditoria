# Retention: does the measured age of the records fit the client's approved retention schedule?
#
# input:
#   category               string  classification of the probed data, e.g. "special_category.health"
#   treatment              string  record of processing activities id, e.g. "HIS-episodes"
#   max_age_days           number  age of the oldest record, measured by the probe
#   out_of_term            number  records older than the applied term; when the challenge does
#                                  not state it, the count the probe brought in input.result.count
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

out_of_term := object.get(input, "out_of_term", object.get(input, ["result", "count"], null))

documented_exceptions := object.get(input, "documented_exceptions", 0)

default compliant := false

compliant if {
	term_days > 0
	input.max_age_days <= term_days
}

# Nothing past the term: the probe counted and found no record older than the calendar allows.
compliant if {
	term_days > 0
	out_of_term == 0
}

# Legitimate exceptions: records past the term, but every one of them documented.
compliant if {
	term_days > 0
	out_of_term > 0
	out_of_term == documented_exceptions
}

verdict := {
	"compliant": compliant,
	"out_of_term": out_of_term,
	"applied_term_days": term_days,
	"rule": "argos.retention",
}
