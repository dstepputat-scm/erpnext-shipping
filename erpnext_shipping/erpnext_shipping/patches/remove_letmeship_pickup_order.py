import frappe


def execute():
	"""The pickup order option was misleading: a normal shipment is picked up anyway."""
	frappe.delete_doc_if_exists("Custom Field", "Shipment-letmeship_pickup_order")
