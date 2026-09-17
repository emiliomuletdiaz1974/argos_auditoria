package argos.access_test

import data.argos.access

client := {"authorized_profiles": {"special_category.health": ["physician", "nurse"]}}

test_only_authorized_profiles_is_compliant if {
	v := access.verdict with data.client as client
		with input as {"target": "his.episodes", "category": "special_category.health", "identities": [{"name": "dr.garcia", "profile": "physician"}, {"name": "nurse.lopez", "profile": "nurse"}]}
	v.compliant
	v.unauthorized == []
	v.total == 2
}

test_identities_without_or_outside_the_profiles_are_listed_sorted if {
	v := access.verdict with data.client as client
		with input as {"target": "his.episodes", "category": "special_category.health", "identities": [{"name": "svc_bi", "profile": null}, {"name": "dr.garcia", "profile": "physician"}, {"name": "admin", "profile": "it"}, {"name": "etl"}]}
	not v.compliant
	v.unauthorized == ["admin", "etl", "svc_bi"]
	v.total == 4
}

test_a_category_without_authorized_profiles_authorizes_nobody if {
	v := access.verdict with data.client as client
		with input as {"target": "hr.payroll", "category": "identifier.national_id", "identities": [{"name": "dr.garcia", "profile": "physician"}]}
	not v.compliant
	v.unauthorized == ["dr.garcia"]
}

test_the_identities_of_the_probe_take_the_profile_the_client_declared if {
	v := access.verdict with data.client as {"authorized_profiles": {"special_category.health": ["physician", "argos_audit"]}, "identity_profiles": {"argos_ro": "argos_audit", "clinic_admin": "physician", "billing_analyst": "billing_clerk"}}
		with input as {"target": "clinic.patients", "category": "special_category.health", "result": {"rows": [{"role_name": "argos_ro"}, {"role_name": "clinic_admin"}]}}
	v.compliant
	v.total == 2
}

test_an_identity_of_the_probe_without_an_authorized_profile_is_listed if {
	v := access.verdict with data.client as {"authorized_profiles": {"special_category.health": ["physician", "argos_audit"]}, "identity_profiles": {"argos_ro": "argos_audit", "billing_analyst": "billing_clerk"}}
		with input as {"target": "billing.patient_mirror", "category": "special_category.health", "result": {"rows": [{"role_name": "argos_ro"}, {"role_name": "billing_analyst"}]}}
	not v.compliant
	v.unauthorized == ["billing_analyst"]
}

test_a_probe_that_brought_no_identity_does_not_absolve if {
	v := access.verdict with data.client as {"authorized_profiles": {"special_category.health": ["physician"]}}
		with input as {"target": "clinic.patients", "category": "special_category.health", "result": {"rows": []}}
	not v.compliant
	v.total == 0
}
