import frappe
from frappe import _


def get_shipment_dashboard_data(data):
	"""Show the Delivery Notes and the Sales Order of a Shipment in its Connections tab."""
	data = frappe._dict(data)
	data.internal_links = data.internal_links or {}
	data.internal_links.update(
		{
			"Delivery Note": ["shipment_delivery_note", "delivery_note"],
			"Sales Order": "sales_order",
		}
	)
	data.transactions = data.transactions or []
	data.transactions.append({"label": _("Reference"), "items": ["Sales Order", "Delivery Note"]})
	return data


def get_sales_order_dashboard_data(data):
	"""Show the Shipments of a Sales Order in its Connections tab."""
	data = frappe._dict(data)
	data.transactions = data.transactions or []
	for group in data.transactions:
		if "Delivery Note" in group.get("items", []):
			group["items"].append("Shipment")
			break
	else:
		data.transactions.append({"label": _("Shipping"), "items": ["Shipment"]})
	return data
