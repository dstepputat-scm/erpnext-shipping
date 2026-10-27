import frappe

DEFAULTS = {
	"notify_recipient": 1,
	"carrier_notification": 1,
	"attach_proof_of_delivery": 1,
	"cancel_at_letmeship": 1,
	"label_size": "default",
}


def execute():
	"""Set defaults for new LetMeShip settings that existing sites don't have yet."""
	for fieldname, value in DEFAULTS.items():
		current = frappe.db.get_value("Singles", {"doctype": "LetMeShip", "field": fieldname}, "value")
		if current is None:
			frappe.db.set_single_value("LetMeShip", fieldname, value)
