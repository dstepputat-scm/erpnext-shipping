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
	# tabSingles has no creation column, so frappe.db.get_value (which orders by creation) can't be used
	existing = set(
		frappe.db.sql_list("select field from `tabSingles` where doctype = %s", ("LetMeShip",))
	)
	for fieldname, value in DEFAULTS.items():
		if fieldname not in existing:
			frappe.db.set_single_value("LetMeShip", fieldname, value)
