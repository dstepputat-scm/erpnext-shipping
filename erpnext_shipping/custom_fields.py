from .utils import identity as _

# Options can be changed on a submitted Shipment until it is booked
LETMESHIP_OPTION = {"allow_on_submit": 1, "read_only_depends_on": "eval:doc.shipment_id"}


def get_custom_fields():
	return {
		"Delivery Note": [
			{
				"fieldname": "shipping_sec_break",
				"label": _("Shipping Details"),
				"fieldtype": "Section Break",
				"collapsible": 1,
				"insert_after": "sales_team",
			},
			{
				"fieldname": "delivery_type",
				"label": _("Delivery Type"),
				"fieldtype": "Data",
				"read_only": 1,
				"translatable": 0,
				"insert_after": "shipping_sec_break",
			},
			{
				"fieldname": "parcel_service",
				"label": _("Parcel Service"),
				"fieldtype": "Data",  # needs to be "Data" for backward compat
				"options": "Parcel Service",
				"read_only": 1,
				"insert_after": "delivery_type",
			},
			{
				"fieldname": "parcel_service_type",
				"label": _("Parcel Service Type"),
				"fieldtype": "Data",  # needs to be "Data" for backward compat
				"options": "Parcel Service Type",
				"read_only": 1,
				"insert_after": "parcel_service",
			},
			{
				"fieldname": "shipping_col_break",
				"fieldtype": "Column Break",
				"insert_after": "parcel_service_type",
			},
			{
				"fieldname": "tracking_number",
				"label": _("Tracking Number"),
				"fieldtype": "Data",
				"read_only": 1,
				"translatable": 0,
				"insert_after": "shipping_col_break",
			},
			{
				"fieldname": "tracking_url",
				"label": _("Tracking URL"),
				"fieldtype": "Small Text",
				"read_only": 1,
				"translatable": 0,
				"insert_after": "tracking_number",
			},
			{
				"fieldname": "tracking_status",
				"label": _("Tracking Status"),
				"fieldtype": "Data",
				"read_only": 1,
				"translatable": 0,
				"insert_after": "tracking_url",
			},
			{
				"fieldname": "tracking_status_info",
				"label": _("Tracking Status Information"),
				"fieldtype": "Data",
				"read_only": 1,
				"translatable": 0,
				"insert_after": "tracking_status",
			},
		],
		"Shipment": [
			{
				"fieldname": "letmeship_section",
				"label": _("LetMeShip Options"),
				"fieldtype": "Section Break",
				"collapsible": 1,
				"insert_after": "description_of_content",
			},
			{
				"fieldname": "letmeship_insurance",
				"label": _("Insure Shipment"),
				"fieldtype": "Check",
				"description": _(
					"Insures the value of goods. Some carriers only insure up to a limit which is shown when selecting the service."
				),
				"insert_after": "letmeship_section",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_saturday_delivery",
				"label": _("Saturday Delivery"),
				"fieldtype": "Check",
				"insert_after": "letmeship_insurance",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_holiday_delivery",
				"label": _("Holiday Delivery"),
				"fieldtype": "Check",
				"insert_after": "letmeship_saturday_delivery",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_pickup_order",
				"label": _("Order Pickup from Carrier"),
				"fieldtype": "Check",
				"insert_after": "letmeship_holiday_delivery",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_pickup_tail_lift",
				"label": _("Tail Lift at Pickup"),
				"fieldtype": "Check",
				"insert_after": "letmeship_pickup_order",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_delivery_tail_lift",
				"label": _("Tail Lift at Delivery"),
				"fieldtype": "Check",
				"insert_after": "letmeship_pickup_tail_lift",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_col_break_payment",
				"fieldtype": "Column Break",
				"insert_after": "letmeship_delivery_tail_lift",
			},
			{
				"fieldname": "letmeship_freight_payer",
				"label": _("Freight Payer"),
				"fieldtype": "Select",
				"options": "Sender\nReceiver\nThird Party",
				"default": "Sender",
				"insert_after": "letmeship_col_break_payment",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_ex_works_account",
				"label": _("Carrier Account Number of Payer"),
				"fieldtype": "Data",
				"translatable": 0,
				"depends_on": "eval:doc.letmeship_freight_payer && doc.letmeship_freight_payer != 'Sender'",
				"mandatory_depends_on": "eval:doc.letmeship_freight_payer && doc.letmeship_freight_payer != 'Sender'",
				"insert_after": "letmeship_freight_payer",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_cash_on_delivery",
				"label": _("Cash on Delivery"),
				"fieldtype": "Check",
				"insert_after": "letmeship_ex_works_account",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_cod_amount",
				"label": _("Cash on Delivery Amount"),
				"fieldtype": "Currency",
				"depends_on": "letmeship_cash_on_delivery",
				"mandatory_depends_on": "letmeship_cash_on_delivery",
				"insert_after": "letmeship_cash_on_delivery",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_col_break_notification",
				"fieldtype": "Column Break",
				"insert_after": "letmeship_cod_amount",
			},
			{
				"fieldname": "letmeship_recipient_emails",
				"label": _("Additional Recipient Notification Emails"),
				"fieldtype": "Small Text",
				"description": _("The delivery contact is notified automatically if enabled in the LetMeShip settings."),
				"insert_after": "letmeship_col_break_notification",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_tracking_emails",
				"label": _("Tracking Notification Emails"),
				"fieldtype": "Small Text",
				"description": _("Notified on delivery and on problems in addition to the LetMeShip settings."),
				"insert_after": "letmeship_recipient_emails",
				**LETMESHIP_OPTION,
			},
			{
				"fieldname": "letmeship_insurance_premium",
				"label": _("Insurance Premium"),
				"fieldtype": "Currency",
				"read_only": 1,
				"depends_on": "letmeship_insurance",
				"insert_after": "shipment_amount",
			},
			{
				"fieldname": "letmeship_service_notes",
				"label": _("Service Notes"),
				"fieldtype": "Small Text",
				"read_only": 1,
				"translatable": 0,
				"depends_on": "letmeship_service_notes",
				"insert_after": "letmeship_insurance_premium",
			},
			{
				"fieldname": "letmeship_tracking_history",
				"label": _("Tracking History"),
				"fieldtype": "Small Text",
				"read_only": 1,
				"translatable": 0,
				"depends_on": "letmeship_tracking_history",
				"insert_after": "tracking_status_info",
			},
		],
	}


def get_fields_for_patch(doctype: str, fieldnames: list[str]) -> dict[str, list[dict]]:
	"""Return specific fields that are needed for a patch."""
	return {doctype: [field for field in get_custom_fields()[doctype] if field["fieldname"] in fieldnames]}
