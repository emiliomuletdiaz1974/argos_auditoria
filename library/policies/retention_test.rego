package argos.retention_test

import data.argos.retention

client := {
	"retention_schedule": {"HIS-episodes": {"days": 5475}},
	"retention_defaults": {"special_category.health": {"days": 1825}},
}

test_within_the_declared_schedule_is_compliant if {
	v := retention.verdict with data.client as client
		with input as {"category": "special_category.health", "treatment": "HIS-episodes", "max_age_days": 4380, "out_of_term": 0, "documented_exceptions": 0}
	v.compliant
	v.applied_term_days == 5475
	v.rule == "argos.retention"
}

test_the_treatment_schedule_wins_over_the_category_default if {
	v := retention.verdict with data.client as client
		with input as {"category": "special_category.health", "treatment": "HIS-episodes", "max_age_days": 2000, "out_of_term": 0, "documented_exceptions": 0}
	v.applied_term_days == 5475
	v.compliant
}

test_without_schedule_the_category_default_applies if {
	v := retention.verdict with data.client as client
		with input as {"category": "special_category.health", "treatment": "LAB-results", "max_age_days": 2000, "out_of_term": 40, "documented_exceptions": 0}
	v.applied_term_days == 1825
	not v.compliant
}

test_all_out_of_term_records_documented_is_compliant if {
	v := retention.verdict with data.client as client
		with input as {"category": "special_category.health", "treatment": "LAB-results", "max_age_days": 2000, "out_of_term": 12, "documented_exceptions": 12}
	v.compliant
}

test_without_any_term_it_is_never_compliant if {
	v := retention.verdict with data.client as client
		with input as {"category": "identifier.national_id", "treatment": "HR-payroll", "max_age_days": 1, "out_of_term": 0, "documented_exceptions": 0}
	v.applied_term_days == 0
	not v.compliant
}

test_the_count_of_the_probe_is_used_when_the_challenge_does_not_state_it if {
	v := retention.verdict with data.client as client
		with input as {"category": "special_category.health", "treatment": "HIS-episodes", "result": {"count": 0}}
	v.compliant
	v.out_of_term == 0
}

test_records_past_the_term_counted_by_the_probe_are_not_compliant if {
	v := retention.verdict with data.client as client
		with input as {"category": "special_category.health", "treatment": "HIS-episodes", "result": {"count": 37}}
	not v.compliant
	v.out_of_term == 37
}

test_without_a_count_nothing_absolves if {
	v := retention.verdict with data.client as client
		with input as {"category": "special_category.health", "treatment": "HIS-episodes", "result": {}}
	not v.compliant
	v.out_of_term == null
}
