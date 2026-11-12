import frappe
from frappe import _

# documents that may link to a Shipment through a custom Link field, e.g. a
# Stock Entry that sends material to a supplier
LINKING_DOCTYPES = ("Stock Entry",)


def get_shipment_dashboard_data(data):
	"""Show the documents of a Shipment in its Connections tab."""
	data = frappe._dict(data)
	data.internal_links = data.internal_links or {}
	data.internal_links.update(
		{
			"Delivery Note": ["shipment_delivery_note", "delivery_note"],
			"Sales Order": "sales_order",
			"Purchase Order": "purchase_order",
		}
	)
	data.non_standard_fieldnames = data.non_standard_fieldnames or {}
	items = ["Sales Order", "Delivery Note", "Purchase Order"]
	for doctype in LINKING_DOCTYPES:
		fieldname = get_shipment_link_field(doctype)
		if fieldname:
			data.non_standard_fieldnames[doctype] = fieldname
			items.append(doctype)

	data.fieldname = data.fieldname or "shipment"
	data.transactions = data.transactions or []
	data.transactions.append({"label": _("Reference"), "items": items})
	return data


def get_order_dashboard_data(data):
	"""Show the Shipments of a Sales or Purchase Order in its Connections tab."""
	data = frappe._dict(data)
	data.transactions = data.transactions or []
	for group in data.transactions:
		if "Delivery Note" in group.get("items", []):
			group["items"].append("Shipment")
			break
	else:
		data.transactions.append({"label": _("Shipping"), "items": ["Shipment"]})
	return data


def get_stock_entry_dashboard_data(data):
	"""Show the Shipment of a Stock Entry in its Connections tab."""
	data = frappe._dict(data)
	fieldname = get_shipment_link_field("Stock Entry")
	if not fieldname:
		return data

	data.internal_links = data.internal_links or {}
	data.internal_links["Shipment"] = fieldname
	data.transactions = data.transactions or []
	data.transactions.append({"label": _("Shipping"), "items": ["Shipment"]})
	return data


def get_shipment_link_field(doctype: str) -> str | None:
	"""Return the first Link field of the DocType that points to a Shipment."""
	fields = frappe.get_meta(doctype).get("fields", {"fieldtype": "Link", "options": "Shipment"})
	return fields[0].fieldname if fields else None
