import frappe


def execute():
	"""Show existing pallet shipments as pallets."""
	frappe.db.sql(
		"""update `tabShipment` set pallets = 'Yes'
		where letmeship_transport_type in ('Pallet', 'Express Pallet')"""
	)
