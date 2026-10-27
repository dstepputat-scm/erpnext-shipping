# Copyright (c) 2020, Frappe Technologies and contributors
# For license information, please see license.txt
import json

import frappe
from erpnext.stock.doctype.shipment.shipment import get_company_contact
from frappe import _

from erpnext_shipping.erpnext_shipping.doctype.letmeship.letmeship import (
	LETMESHIP_PROVIDER,
	get_letmeship_utils,
	get_shipment_options,
)
from erpnext_shipping.erpnext_shipping.doctype.sendcloud.sendcloud import SENDCLOUD_PROVIDER, SendCloudUtils
from erpnext_shipping.erpnext_shipping.utils import (
	get_address,
	get_contact,
	match_parcel_service_type_carrier,
)


@frappe.whitelist()
def fetch_shipping_rates(
	pickup_from_type,
	delivery_to_type,
	pickup_address_name,
	delivery_address_name,
	parcels,
	description_of_content,
	pickup_date,
	value_of_goods,
	pickup_contact_name=None,
	delivery_contact_name=None,
	shipment=None,
):
	# Return Shipping Rates for the various Shipping Providers
	shipment_prices = []
	letmeship_enabled = frappe.db.get_single_value("LetMeShip", "enabled")
	sendcloud_enabled = frappe.db.get_single_value("SendCloud", "enabled")
	pickup_address = get_address(pickup_address_name)
	delivery_address = get_address(delivery_address_name)
	parcels = json.loads(parcels)

	if letmeship_enabled:
		pickup_contact = None
		delivery_contact = None
		if pickup_from_type != "Company":
			pickup_contact = get_contact(pickup_contact_name)
		else:
			pickup_contact = get_company_contact(user=pickup_contact_name)
			pickup_contact.email_id = pickup_contact.pop("email", None)

		delivery_contact = get_contact(delivery_contact_name)

		letmeship = get_letmeship_utils()
		letmeship_prices = (
			letmeship.get_available_services(
				delivery_to_type=delivery_to_type,
				pickup_address=pickup_address,
				delivery_address=delivery_address,
				parcels=parcels,
				description_of_content=description_of_content,
				pickup_date=pickup_date,
				value_of_goods=value_of_goods,
				pickup_contact=pickup_contact,
				delivery_contact=delivery_contact,
				options=get_shipment_options(shipment) if shipment else None,
			)
			or []
		)
		letmeship_prices = match_parcel_service_type_carrier(letmeship_prices, "carrier", "service_name")
		shipment_prices += letmeship_prices

	if sendcloud_enabled:
		sendcloud = SendCloudUtils()
		sendcloud_prices = (
			sendcloud.get_available_services(
				delivery_address=delivery_address, pickup_address=pickup_address, parcels=parcels
			)
			or []
		)
		sendcloud_prices = match_parcel_service_type_carrier(sendcloud_prices, "carrier", "service_name")
		shipment_prices += sendcloud_prices

	shipment_prices = [item for item in shipment_prices if "total_price" in item]
	shipment_prices = sorted(shipment_prices, key=lambda k: k["total_price"])
	return shipment_prices


@frappe.whitelist()
def create_shipment(
	shipment,
	pickup_from_type,
	delivery_to_type,
	pickup_address_name,
	delivery_address_name,
	shipment_parcel,
	description_of_content,
	pickup_date,
	value_of_goods,
	service_data,
	shipment_notific_email=None,
	tracking_notific_email=None,
	pickup_contact_name=None,
	delivery_contact_name=None,
	delivery_notes=None,
):
	if isinstance(delivery_notes, str):
		delivery_notes = json.loads(delivery_notes)

	if delivery_notes is None:
		delivery_notes = []

	service_info = json.loads(service_data)
	shipment_info, pickup_contact, delivery_contact = None, None, None
	pickup_address = get_address(pickup_address_name)
	delivery_address = get_address(delivery_address_name)
	delivery_company_name = get_delivery_company_name(shipment)

	if pickup_from_type != "Company":
		pickup_contact = get_contact(pickup_contact_name)

	else:
		pickup_contact = get_company_contact(user=pickup_contact_name)
		pickup_contact.email_id = pickup_contact.pop("email", None)

	delivery_contact = get_contact(delivery_contact_name)

	if service_info["service_provider"] == LETMESHIP_PROVIDER:
		letmeship = get_letmeship_utils()
		shipment_info = letmeship.create_shipment(
			pickup_address=pickup_address,
			delivery_company_name=delivery_company_name,
			delivery_address=delivery_address,
			shipment_parcel=shipment_parcel,
			description_of_content=description_of_content,
			pickup_date=pickup_date,
			value_of_goods=value_of_goods,
			pickup_contact=pickup_contact,
			delivery_contact=delivery_contact,
			service_info=service_info,
			options=get_shipment_options(shipment),
		)

	if service_info["service_provider"] == SENDCLOUD_PROVIDER:
		sendcloud = SendCloudUtils()
		shipment_info = sendcloud.create_shipment(
			shipment=shipment,
			delivery_address=delivery_address,
			pickup_address=pickup_address,
			pickup_contact=pickup_contact,
			shipment_parcel=shipment_parcel,
			delivery_contact=delivery_contact,
			service_info=service_info,
		)

	if shipment_info:
		shipment = frappe.get_doc("Shipment", shipment)
		shipment.db_set(
			{
				"service_provider": shipment_info.get("service_provider"),
				"carrier": shipment_info.get("carrier"),
				"carrier_service": shipment_info.get("carrier_service"),
				"shipment_id": shipment_info.get("shipment_id"),
				"shipment_amount": shipment_info.get("shipment_amount"),
				"awb_number": shipment_info.get("awb_number"),
				"status": "Booked",
			}
		)

		if shipment_info.get("service_provider") == LETMESHIP_PROVIDER:
			shipment.db_set(
				{
					"letmeship_insurance_premium": shipment_info.get("insurance_premium"),
					"letmeship_service_notes": shipment_info.get("service_notes"),
				}
			)

		if delivery_notes:
			update_delivery_note(delivery_notes=delivery_notes, shipment_info=shipment_info)

	return shipment_info


def cancel_shipment_with_provider(doc, method=None):
	"""Cancel the booking at the provider before the Shipment gets cancelled.

	Throws if the provider refuses, so ERPNext and the provider stay in sync.
	"""
	if doc.service_provider != LETMESHIP_PROVIDER or not doc.shipment_id:
		return

	if not frappe.db.get_single_value("LetMeShip", "enabled") or not frappe.db.get_single_value(
		"LetMeShip", "cancel_at_letmeship"
	):
		return

	get_letmeship_utils().cancel_shipment(doc.shipment_id)
	doc.add_comment("Info", _("Shipment {0} was cancelled at LetMeShip.").format(doc.shipment_id))


def get_delivery_company_name(shipment: str) -> str | None:
	shipment_doc = frappe.get_doc("Shipment", shipment)
	if shipment_doc.delivery_customer:
		return frappe.db.get_value("Customer", shipment_doc.delivery_customer, "customer_name")
	if shipment_doc.delivery_supplier:
		return frappe.db.get_value("Supplier", shipment_doc.delivery_supplier, "supplier_name")
	if shipment_doc.delivery_company:
		return frappe.db.get_value("Company", shipment_doc.delivery_company, "company_name")

	return None


@frappe.whitelist()
def print_shipping_label(shipment: str):
	shipment_doc = frappe.get_doc("Shipment", shipment)
	service_provider = shipment_doc.service_provider
	shipment_id = shipment_doc.shipment_id

	if service_provider == LETMESHIP_PROVIDER:
		letmeship = get_letmeship_utils()
		shipping_label = letmeship.get_label(shipment_id)
	elif service_provider == SENDCLOUD_PROVIDER:
		sendcloud = SendCloudUtils()
		shipping_label = []
		_labels = sendcloud.get_label(shipment_id)
		for i, label_url in enumerate(_labels, start=1):
			content = sendcloud.download_label(label_url)
			file_url = save_label_as_attachment(shipment, content, i)
			shipping_label.append(file_url)

	return shipping_label


@frappe.whitelist()
def fetch_proof_of_delivery(shipment: str):
	"""Return the URL of the proof of delivery, attaching it to the Shipment if needed."""
	shipment_doc = frappe.get_doc("Shipment", shipment)
	shipment_doc.check_permission("read")

	if file_url := get_proof_of_delivery_file(shipment):
		return file_url

	file_url = attach_proof_of_delivery(shipment, shipment_doc.shipment_id)
	if not file_url:
		frappe.throw(_("The proof of delivery is not available yet."))

	return file_url


def attach_proof_of_delivery(shipment: str, shipment_id: str) -> str | None:
	content = get_letmeship_utils().get_proof_of_delivery(shipment_id)
	if not content:
		return None

	return save_attachment(shipment, f"pod_{shipment}.pdf", content)


def get_proof_of_delivery_file(shipment: str) -> str | None:
	return frappe.db.get_value(
		"File",
		{"attached_to_doctype": "Shipment", "attached_to_name": shipment, "file_name": f"pod_{shipment}.pdf"},
		"file_url",
	)


def save_label_as_attachment(shipment: str, content: bytes, index: int = None) -> str:
	"""Store label as attachment to Shipment and return the URL."""
	if index is not None:
		file_name = f"label_{shipment}_{index}.pdf"
	else:
		file_name = f"label_{shipment}.pdf"

	return save_attachment(shipment, file_name, content)


def save_attachment(shipment: str, file_name: str, content: bytes) -> str:
	"""Store a file as attachment to Shipment and return the URL."""
	attachment = frappe.new_doc("File")
	attachment.file_name = file_name
	attachment.content = content
	attachment.folder = "Home/Attachments"
	attachment.attached_to_doctype = "Shipment"
	attachment.attached_to_name = shipment
	attachment.is_private = 1
	attachment.save()
	return attachment.file_url


@frappe.whitelist()
def update_tracking(shipment, service_provider, shipment_id, delivery_notes=None):
	if isinstance(delivery_notes, str):
		delivery_notes = json.loads(delivery_notes)

	if delivery_notes is None:
		delivery_notes = []

	# Update Tracking info in Shipment
	tracking_data = None
	if service_provider == LETMESHIP_PROVIDER:
		letmeship = get_letmeship_utils()
		tracking_data = letmeship.get_tracking_data(shipment_id)
	elif service_provider == SENDCLOUD_PROVIDER:
		sendcloud = SendCloudUtils()
		tracking_data = sendcloud.get_tracking_data(shipment_id)

	if not tracking_data:
		return

	shipment = frappe.get_doc("Shipment", shipment)
	values = {
		"awb_number": tracking_data.get("awb_number"),
		"tracking_status": tracking_data.get("tracking_status"),
		"tracking_status_info": tracking_data.get("tracking_status_info"),
		"tracking_url": tracking_data.get("tracking_url"),
	}
	if service_provider == LETMESHIP_PROVIDER:
		values["letmeship_tracking_history"] = tracking_data.get("tracking_history")

	shipment.db_set(values)

	if (
		service_provider == LETMESHIP_PROVIDER
		and tracking_data.get("tracking_status") == "Delivered"
		and frappe.db.get_single_value("LetMeShip", "attach_proof_of_delivery")
		and not get_proof_of_delivery_file(shipment.name)
	):
		attach_proof_of_delivery(shipment.name, shipment_id)

	if delivery_notes:
		update_delivery_note(delivery_notes=delivery_notes, tracking_info=tracking_data)


def update_delivery_note(delivery_notes, shipment_info=None, tracking_info=None):
	# Update Shipment Info in Delivery Note
	# Using db_set since some services might not exist
	delivery_notes = list(set(delivery_notes))

	for delivery_note in delivery_notes:
		dl_doc = frappe.get_doc("Delivery Note", delivery_note)
		if shipment_info:
			dl_doc.db_set("delivery_type", "Parcel Service")
			dl_doc.db_set("parcel_service", shipment_info.get("carrier"))
			dl_doc.db_set("parcel_service_type", shipment_info.get("carrier_service"))
		if tracking_info:
			dl_doc.db_set("tracking_number", tracking_info.get("awb_number"))
			dl_doc.db_set("tracking_url", tracking_info.get("tracking_url"))
			dl_doc.db_set("tracking_status", tracking_info.get("tracking_status"))
			dl_doc.db_set("tracking_status_info", tracking_info.get("tracking_status_info"))
