# Copyright (c) 2020, Frappe Technologies and contributors
# For license information, please see license.txt

import base64
import json
import re
from json import dumps as json_dumps

import frappe
import requests
from frappe import _
from frappe.model.document import Document
from frappe.utils import split_emails
from frappe.utils.data import cint, flt, get_link_to_form, get_time
from requests.exceptions import HTTPError

from erpnext_shipping.erpnext_shipping.utils import show_error_alert

LETMESHIP_PROVIDER = "LetMeShip"
PROD_BASE_URL = "https://api.letmeship.com/v1"
TEST_BASE_URL = "https://api.test.letmeship.com/v1"

# Freight payer on the Shipment -> LetMeShip ExWorks type
EX_WORKS_TYPES = {"Receiver": "RECEIVER_PAYS", "Third Party": "THIRD_PARTY_PAYS"}
CASH_ON_DELIVERY = "CASH_ON_DELIVERY"
CANCELLED_STATES = ("CANCEL_REQUESTED", "CANCELLED")
# Service flags that ask for additional customs data or documents
CUSTOMS_REQUIREMENTS = {
	"isInvoiceRequired": "Commercial Invoice",
	"isEoriRequired": "EORI Number",
	"isMrnRequired": "MRN",
	"isEadDocumentRequired": "Export Accompanying Document",
	"isCinDataRequired": "CIN Data",
	"isTddRequired": "Paperless Trade Documents",
}
# Carriers report insurance limits only as free text, e.g. "Shipment can be insured up to 520.00 €."
INSURANCE_LIMIT_PATTERN = re.compile(r"insured up to\s*([\d.,]+)", re.IGNORECASE)


class LetMeShip(Document):
	def validate(self):
		if not self.enabled:
			return

		utils = LetMeShipUtils(
			base_url=TEST_BASE_URL if self.use_test_environment else PROD_BASE_URL,
			api_id=self.api_id,
			api_password=self.get_password("api_password"),
		)

		try:
			utils.request("GET", "documents")  # check if the API and credentials are working
		except HTTPError as e:
			if e.response.status_code == 401:
				frappe.throw(_("Invalid API ID or Password"))
			else:
				frappe.throw(
					_("There was an error with the LetMeShip API. HTTP Status Code: {0}").format(
						e.response.status_code
					)
				)


class LetMeShipUtils:
	def __init__(self, base_url: str, api_id: str, api_password: str, settings=None):
		self.base_url = base_url
		self.api_password = api_password
		self.api_id = api_id
		self.settings = settings or frappe._dict()

	def request(self, method: str, endpoint: str, json: dict | None = None, params: dict | None = None):
		"""Make a request to LetMeShip API."""
		response = requests.request(
			method,
			f"{self.base_url}/{endpoint}",
			auth=(self.api_id, self.api_password),
			headers={
				"Content-Type": "application/json",
				"Accept": "application/json",
				"Access-Control-Allow-Origin": "string",
			},
			params=params,
			json=json,
		)

		response.raise_for_status()

		data = response.json()
		if "status" in data and data["status"]["code"] != "0":
			frappe.throw(
				_("An Error occurred while fetching LetMeShip {0}:\n{1}").format(
					endpoint, json_dumps(data["status"], indent=4)
				)
			)

		return data

	def get_available_services(
		self,
		delivery_to_type,
		pickup_address,
		delivery_address,
		parcels,
		description_of_content,
		pickup_date,
		value_of_goods,
		pickup_contact=None,
		delivery_contact=None,
		options=None,
	):
		if not self.validate_parcels(parcels):
			frappe.msgprint(
				_("LetMeShip rates need parcel dimensions (length, width, height)."),
				indicator="orange",
				alert=True,
			)
			return []

		options = options or frappe._dict()
		self.set_letmeship_specific_fields(pickup_contact, delivery_contact)
		pickup_address.address_title = self.first_30_chars(pickup_address.address_title)
		delivery_address.address_title = self.first_30_chars(delivery_address.address_title)
		parcel_list = self.get_parcel_list(parcels, description_of_content, options.cash_on_delivery)
		payload = self.generate_payload(
			pickup_address=pickup_address,
			pickup_contact=pickup_contact,
			delivery_address=delivery_address,
			delivery_contact=delivery_contact,
			description_of_content=description_of_content,
			value_of_goods=value_of_goods,
			parcel_list=parcel_list,
			pickup_date=pickup_date,
			options=options,
		)

		try:
			response_data = self.request("POST", "available", json=payload)
			if "serviceList" in response_data and response_data["serviceList"]:
				required_ex_work_type = self.get_required_ex_work_type(options)
				available_services = []
				for response in response_data["serviceList"]:
					if required_ex_work_type and required_ex_work_type not in (
						response.get("supportedExWorkType") or []
					):
						continue

					available_service = self.get_service_dict(response, options, value_of_goods)
					available_services.append(available_service)

				return available_services
		except Exception:
			show_error_alert("fetching LetMeShip prices")

		return []

	def create_shipment(
		self,
		pickup_address,
		delivery_company_name,
		delivery_address,
		shipment_parcel,
		description_of_content,
		pickup_date,
		value_of_goods,
		service_info,
		pickup_contact=None,
		delivery_contact=None,
		options=None,
	):
		parcels = json.loads(shipment_parcel)
		if not self.validate_parcels(parcels):
			frappe.throw(_("LetMeShip booking needs parcel dimensions (length, width, height)."))

		options = options or frappe._dict()
		self.set_letmeship_specific_fields(pickup_contact, delivery_contact)
		pickup_address.address_title = self.first_30_chars(pickup_address.address_title)
		delivery_address.address_title = self.first_30_chars(
			delivery_company_name or delivery_address.address_title
		)
		parcel_list = self.get_parcel_list(parcels, description_of_content, options.cash_on_delivery)

		payload = self.generate_payload(
			pickup_address=pickup_address,
			pickup_contact=pickup_contact,
			delivery_address=delivery_address,
			delivery_contact=delivery_contact,
			description_of_content=description_of_content,
			value_of_goods=value_of_goods,
			parcel_list=parcel_list,
			pickup_date=pickup_date,
			service_info=service_info,
			options=options,
		)
		try:
			response_data = self.request("POST", "shipments", json=payload)
			if "shipmentId" in response_data:
				price_info = response_data["service"]["baseServiceDetails"]["priceInfo"]
				shipment_id = response_data["shipmentId"]

				return {
					"service_provider": LETMESHIP_PROVIDER,
					"shipment_id": shipment_id,
					"carrier": response_data["service"]["baseServiceDetails"]["carrier"],
					"carrier_service": response_data["service"]["baseServiceDetails"]["name"],
					"shipment_amount": price_info["totalPrice"],
					"insurance_premium": self.get_insurance_premium(price_info) if options.insurance else 0,
					"service_notes": "\n".join(self.get_messages(response_data["service"])),
					"awb_number": self.get_awb_number(shipment_id),
				}
		except Exception:
			show_error_alert("creating LetMeShip Shipment")

	def cancel_shipment(self, shipment_id):
		"""Cancel a booked shipment. Throws if LetMeShip refuses the cancellation."""
		if self.get_shipment_state(shipment_id) in CANCELLED_STATES:
			return

		try:
			response_data = self.request("DELETE", f"shipments/{shipment_id}")
		except HTTPError as e:
			frappe.throw(
				_("LetMeShip could not cancel Shipment {0}. HTTP Status Code: {1}").format(
					shipment_id, e.response.status_code
				),
				title=_("Cancellation failed"),
			)

		if response_data.get("cancellationState") != "SUCCESSFUL":
			frappe.throw(
				_("LetMeShip could not cancel Shipment {0}: {1}").format(
					shipment_id, response_data.get("details") or response_data.get("cancellationState")
				),
				title=_("Cancellation failed"),
			)

	def get_shipment_state(self, shipment_id):
		try:
			response_data = self.request("GET", f"shipments/{shipment_id}/states")
		except HTTPError:
			return None

		if isinstance(response_data, list):
			response_data = response_data[0] if response_data else {}

		return response_data.get("shipmentState")

	def get_awb_number(self, shipment_id: str):
		shipment_data = self.request("GET", f"shipments/{shipment_id}")
		if "trackingData" in shipment_data:
			return shipment_data["trackingData"].get("awbNumber", "")

		return ""

	def get_label(self, shipment_id):
		try:
			shipment_label_response_data = self.request(
				"GET", f"shipments/{shipment_id}/documents", params={"types": "LABEL"}
			)
			if "documents" in shipment_label_response_data:
				for label in shipment_label_response_data["documents"]:
					if "data" in label:
						return json.dumps(label["data"])
			else:
				frappe.throw(
					_("Error occurred while printing Shipment: {0}").format(
						shipment_label_response_data["message"]
					)
				)
		except Exception:
			show_error_alert("printing LetMeShip Label")

	def get_proof_of_delivery(self, shipment_id) -> bytes | None:
		try:
			response_data = self.request(
				"GET", f"shipments/{shipment_id}/documents", params={"types": "POD"}
			)
		except Exception:
			show_error_alert("fetching LetMeShip Proof of Delivery")
			return None

		for document in response_data.get("documents") or []:
			if document.get("type") == "POD" and document.get("status", "READY") == "READY":
				return decode_document_data(document)

		return None

	def get_tracking_data(self, shipment_id):
		from erpnext_shipping.erpnext_shipping.utils import get_tracking_url

		try:
			tracking_data = self.request("GET", "tracking", params={"shipmentid": shipment_id})

			if "awbNumber" in tracking_data:
				tracking_status = "In Progress"
				if tracking_data["lmsTrackingStatus"].startswith("DELIVERED"):
					tracking_status = "Delivered"
				if tracking_data["lmsTrackingStatus"] == "RETURNED":
					tracking_status = "Returned"
				if tracking_data["lmsTrackingStatus"] == "LOST":
					tracking_status = "Lost"
				tracking_url = get_tracking_url(
					carrier=tracking_data["carrier"], tracking_number=tracking_data["awbNumber"]
				)
				return {
					"awb_number": tracking_data["awbNumber"],
					"tracking_status": tracking_status,
					"tracking_status_info": tracking_data["lmsTrackingStatus"],
					"tracking_url": tracking_url,
					"tracking_history": self.format_tracking_events(tracking_data.get("trackingEventList")),
				}
			elif "message" in tracking_data:
				frappe.throw(
					_("Error occurred while updating Shipment: {0}").format(tracking_data["message"])
				)
		except Exception:
			show_error_alert("updating LetMeShip Shipment")

	def format_tracking_events(self, events):
		"""Return the tracking events as text, newest first."""
		lines = []
		for event in sorted(events or [], key=lambda e: e.get("dateTime") or "", reverse=True):
			parts = (
				event.get("dateTime"),
				event.get("location"),
				event.get("description") or event.get("trackingStatus"),
			)
			lines.append(" · ".join(part for part in parts if part))

		return "\n".join(lines)

	def generate_payload(
		self,
		pickup_address,
		pickup_contact,
		delivery_address,
		delivery_contact,
		description_of_content,
		value_of_goods,
		parcel_list,
		pickup_date,
		service_info=None,
		options=None,
	):
		options = options or frappe._dict()
		shipment_details = {
			"contentDescription": description_of_content,
			"shipmentType": "PARCEL",
			"shipmentSettings": {
				"saturdayDelivery": bool(options.saturday_delivery),
				"ddp": bool(options.ddp),
				"insurance": bool(options.insurance),
				"pickupOrder": bool(options.pickup_order),
				"pickupTailLift": bool(options.pickup_tail_lift),
				"deliveryTailLift": bool(options.delivery_tail_lift),
				"holidayDelivery": bool(options.holiday_delivery),
			},
			"goodsValue": float(value_of_goods),
			"parcelList": parcel_list,
			"pickupInterval": self.get_pickup_interval(pickup_date, options),
		}

		if options.ex_works_type:
			shipment_details["exWorks"] = {
				"exworkType": options.ex_works_type,
				"accountNumber": options.ex_works_account or "",
			}

		if options.reference:
			shipment_details["defaultReferenceCode"] = options.reference

		payload = {
			"pickupInfo": self.get_pickup_delivery_info(pickup_address, pickup_contact),
			"deliveryInfo": self.get_pickup_delivery_info(delivery_address, delivery_contact),
			"shipmentDetails": shipment_details,
		}

		if service_info:
			payload["service"] = {
				"baseServiceDetails": {
					"id": service_info["id"],
					"name": service_info["service_name"],
					"carrier": service_info["carrier"],
					"priceInfo": service_info["price_info"],
				},
				"supportedExWorkType": [],
				"messages": [""],
				"description": "",
				"serviceInfo": "",
			}
			payload["shipmentNotification"] = self.get_shipment_notification(delivery_contact, options)
			payload["labelOptions"] = {"labelSize": self.settings.label_size or "default"}
			payload["labelEmail"] = True
		return payload

	def get_pickup_interval(self, pickup_date, options):
		pickup_interval = {"date": pickup_date}
		if options.pickup_from:
			pickup_interval["timeFrom"] = get_time(options.pickup_from).strftime("%H:%M")
		if options.pickup_to:
			pickup_interval["timeTo"] = get_time(options.pickup_to).strftime("%H:%M")

		return pickup_interval

	def get_shipment_notification(self, delivery_contact, options):
		recipient_emails = []
		if self.settings.notify_recipient and delivery_contact.email_id:
			recipient_emails.append(delivery_contact.email_id)
		recipient_emails += split_emails(options.recipient_emails or "")

		tracking_emails = split_emails(self.settings.tracking_notification_emails or "")
		tracking_emails += split_emails(options.tracking_emails or "")

		notification = {
			"trackingNotification": {
				"deliveryNotification": True,
				"problemNotification": True,
				"emails": list(dict.fromkeys(tracking_emails)),
				"notificationText": "",
			},
			"recipientNotification": {
				"notificationText": self.settings.notification_text or "",
				"emails": list(dict.fromkeys(recipient_emails)),
			},
		}

		if self.settings.carrier_notification:
			carrier_notification = {}
			if delivery_contact.email_id:
				carrier_notification["email"] = delivery_contact.email_id

			mobile_no = (delivery_contact.get("mobile_no") or "").strip()
			if mobile_no.startswith("+"):
				carrier_notification["mobilePhone"] = {
					"phoneNumberPrefix": mobile_no[:3],
					"phoneNumber": re.sub("[^0-9]+", "", mobile_no[3:]),
				}

			if carrier_notification:
				# "addtional" is spelled like this in the LetMeShip API
				notification["addtionalCarrierNotification"] = carrier_notification

		return notification

	def first_30_chars(self, address_title: str):
		# LetMeShip has a limit of 30 characters for Company field
		return address_title[:30] if len(address_title) > 30 else address_title

	def get_service_dict(self, response, options=None, value_of_goods=0):
		"""Returns a dictionary with service info."""
		options = options or frappe._dict()
		available_service = frappe._dict()
		basic_info = response["baseServiceDetails"]
		price_info = basic_info["priceInfo"]
		available_service.service_provider = LETMESHIP_PROVIDER
		available_service.id = basic_info["id"]
		available_service.carrier = basic_info["carrier"]
		available_service.carrier_name = basic_info["carrier"]
		available_service.service_name = basic_info["name"]
		available_service.is_preferred = 0
		available_service.real_weight = price_info["realWeight"]
		available_service.total_price = price_info["netPrice"]
		available_service.price_info = price_info
		available_service.currency = "EUR"
		available_service.messages = self.get_messages(response)
		available_service.customs_requirements = [
			_(label) for key, label in CUSTOMS_REQUIREMENTS.items() if response.get(key)
		]

		if options.insurance:
			available_service.insurance = 1
			available_service.insurance_premium = self.get_insurance_premium(price_info)
			insurance_limit = self.get_insurance_limit(available_service.messages)
			if insurance_limit and insurance_limit < flt(value_of_goods):
				available_service.insurance_limit = insurance_limit

		return available_service

	def get_messages(self, service):
		return [message.strip() for message in service.get("messages") or [] if message and message.strip()]

	def get_insurance_premium(self, price_info):
		"""Sum of the insurance surcharges. 0 means the insurance is included in the price."""
		surcharges = (price_info.get("surcharges") or []) + (price_info.get("specialSurcharges") or [])
		return sum(
			flt(surcharge.get("amount"))
			for surcharge in surcharges
			if "insurance" in (surcharge.get("name") or "").lower()
		)

	def get_insurance_limit(self, messages):
		for message in messages:
			if match := INSURANCE_LIMIT_PATTERN.search(message):
				return parse_amount(match.group(1))

		return None

	def get_required_ex_work_type(self, options):
		return CASH_ON_DELIVERY if options.cash_on_delivery else options.ex_works_type

	def set_letmeship_specific_fields(self, pickup_contact, delivery_contact):
		pickup_contact.phone_prefix = pickup_contact.phone[:3]
		pickup_contact.phone = re.sub("[^A-Za-z0-9]+", "", pickup_contact.phone[3:])

		pickup_contact.title = "MS"
		if pickup_contact.gender == "Male":
			pickup_contact.title = "MR"

		delivery_contact.phone_prefix = delivery_contact.phone[:3]
		delivery_contact.phone = re.sub("[^A-Za-z0-9]+", "", delivery_contact.phone[3:])

		delivery_contact.title = "MS"
		if delivery_contact.gender == "Male":
			delivery_contact.title = "MR"

	def get_parcel_list(self, parcels, description_of_content, cash_on_delivery=None):
		parcel_list = []
		for parcel in parcels:
			if cint(parcel.get("count")) < 1:
				continue

			formatted_parcel = {}
			formatted_parcel["height"] = cint(parcel.get("height"))
			formatted_parcel["width"] = cint(parcel.get("width"))
			formatted_parcel["length"] = cint(parcel.get("length"))
			formatted_parcel["weight"] = flt(parcel.get("weight"))
			formatted_parcel["quantity"] = cint(parcel.get("count"))
			formatted_parcel["contentDescription"] = description_of_content
			parcel_list.append(formatted_parcel)

		if cash_on_delivery and parcel_list:
			# the amount is collected once per shipment
			parcel_list[0]["cashOnDelivery"] = {"value": flt(cash_on_delivery, 2), "currency": "EUR"}

		return parcel_list

	def get_pickup_delivery_info(self, address, contact):
		return {
			"address": {
				"countryCode": address.country_code,
				"zip": address.pincode,
				"city": address.city,
				"street": address.address_line1,
				"addressInfo1": address.address_line2,
				"houseNo": "",
			},
			"company": address.address_title,
			"person": {
				"title": contact.title,
				"firstname": contact.first_name,
				"lastname": contact.last_name,
			},
			"phone": {"phoneNumber": contact.phone, "phoneNumberPrefix": contact.phone_prefix},
			"email": contact.email_id,
		}

	def validate_parcels(self, parcels):
		for parcel in parcels:
			for field in ("length", "width", "height"):
				if (parcel.get(field) or 0) < 1:
					return False
		return True


def get_letmeship_utils() -> "LetMeShipUtils":
	settings = frappe.get_single("LetMeShip")
	if not settings.enabled:
		link = get_link_to_form("LetMeShip", "LetMeShip", frappe.bold("LetMeShip Settings"))
		frappe.throw(_(f"Please enable LetMeShip Integration in {link}"), title=_("Mandatory"))

	return LetMeShipUtils(
		base_url=TEST_BASE_URL if settings.use_test_environment else PROD_BASE_URL,
		api_id=settings.api_id,
		api_password=settings.get_password("api_password"),
		settings=settings,
	)


def get_shipment_options(shipment) -> frappe._dict:
	"""Return the LetMeShip specific options of a Shipment."""
	doc = frappe.get_doc("Shipment", shipment) if isinstance(shipment, str) else shipment
	delivery_notes = [row.delivery_note for row in doc.get("shipment_delivery_note") or []]

	return frappe._dict(
		insurance=doc.get("letmeship_insurance"),
		saturday_delivery=doc.get("letmeship_saturday_delivery"),
		holiday_delivery=doc.get("letmeship_holiday_delivery"),
		pickup_order=doc.get("letmeship_pickup_order"),
		pickup_tail_lift=doc.get("letmeship_pickup_tail_lift"),
		delivery_tail_lift=doc.get("letmeship_delivery_tail_lift"),
		ddp=doc.get("incoterm") == "DDP",
		ex_works_type=EX_WORKS_TYPES.get(doc.get("letmeship_freight_payer")),
		ex_works_account=doc.get("letmeship_ex_works_account"),
		cash_on_delivery=flt(doc.get("letmeship_cod_amount")) if doc.get("letmeship_cash_on_delivery") else 0,
		pickup_from=doc.get("pickup_from"),
		pickup_to=doc.get("pickup_to"),
		reference=(", ".join(delivery_notes) or doc.name)[:35],
		recipient_emails=doc.get("letmeship_recipient_emails"),
		tracking_emails=doc.get("letmeship_tracking_emails"),
	)


def parse_amount(value: str) -> float:
	"""Parse an amount like "520.00", "1.000", "1.000,50" or "1,000.50"."""
	value = value.rstrip(".,")
	if "," in value and "." in value:
		if value.rfind(",") > value.rfind("."):
			value = value.replace(".", "").replace(",", ".")
		else:
			value = value.replace(",", "")
	elif re.fullmatch(r"\d{1,3}([.,]\d{3})+", value):
		value = re.sub("[.,]", "", value)
	else:
		value = value.replace(",", ".")

	return flt(value)


def decode_document_data(document: dict) -> bytes | None:
	"""Return the file content of a LetMeShip document."""
	if document.get("dataEncoded"):
		return base64.b64decode(document["dataEncoded"])

	data = document.get("data")
	if isinstance(data, list):
		return bytes(data)
	if isinstance(data, str):
		return base64.b64decode(data)

	return None
