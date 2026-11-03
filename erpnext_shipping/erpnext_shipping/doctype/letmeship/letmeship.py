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
from frappe.utils import escape_html, split_emails
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
# Address fields LetMeShip requires besides country and pincode, which get_address already checks
REQUIRED_ADDRESS_FIELDS = {"address_line1": "Address Line 1", "city": "City"}
# Most parcel services only carry parcels up to this weight (kg)
PARCEL_WEIGHT_LIMIT = 31.5
# Transport type on the Shipment -> LetMeShip transportType
TRANSPORT_TYPES = {
	"Parcel": "STANDARD",
	"Express Parcel": "EXPRESS",
	"Pallet": "STANDARD_PALETTE",
	"Express Pallet": "EXPRESS_PALETTE",
	"Same Day": "SAMEDAY",
	"Freight": "FREIGHT",
}
# LetMeShip lists services even if the shipment exceeds their limits and only says so in a message
UNSUITABLE_SERVICE_PATTERN = re.compile(
	r"exceeded|not possible|(?:doesn't|does not) support|please enter", re.IGNORECASE
)


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

		if not response.ok:
			# keep LetMeShip's error details, raise_for_status() only reports the status code
			raise HTTPError(
				f"{response.status_code} {response.reason} for url: {response.url}\n{response.text}",
				response=response,
			)

		data = response.json()
		if "status" in data and data["status"]["code"] != "0":
			frappe.throw(
				_("LetMeShip rejected the request: {0}").format(get_error_message(data)),
				title=_("LetMeShip Error"),
			)

		return data

	def throw_request_error(self, error: HTTPError, parcels=None):
		"""Log the failed request and tell the user what went wrong in plain words."""
		status_code = error.response.status_code
		log = frappe.log_error(title="LetMeShip Error")
		details = get_link_to_form("Error Log", log.name, _("Details"))

		if status_code == 401:
			message = _("The API ID or password in the {0} is not valid.").format(
				get_link_to_form("LetMeShip", "LetMeShip", _("LetMeShip settings"))
			)
		elif status_code >= 500:
			message = _(
				"LetMeShip is not available right now or had an internal error (HTTP {0}). Please try again later."
			).format(status_code)
		else:
			message = _("LetMeShip rejected the request (HTTP {0}): {1}").format(
				status_code, frappe.bold(escape_html(get_error_message(error.response)))
			)

		hints = self.get_parcel_hints(parcels or [])
		frappe.throw(
			"<br>".join([message, *hints, details]),
			title=_("LetMeShip Error"),
		)

	def validate_request_data(self, pickup_address, delivery_address, pickup_contact, delivery_contact, parcels):
		"""Throw one message listing everything LetMeShip needs but the Shipment lacks."""
		problems = []
		for label, address in (
			(_("Pickup Address"), pickup_address),
			(_("Delivery Address"), delivery_address),
		):
			missing = [
				_(field_label)
				for fieldname, field_label in REQUIRED_ADDRESS_FIELDS.items()
				if not (address.get(fieldname) or "").strip()
			]
			if missing:
				problems.append(
					_("{0} {1}: {2} missing").format(
						label, get_link_to_form("Address", address.name), ", ".join(missing)
					)
				)

		for label, contact in (
			(_("Pickup Contact"), pickup_contact),
			(_("Delivery Contact"), delivery_contact),
		):
			if contact.get("name"):
				label = f"{label} {get_link_to_form('Contact', contact.name)}"

			phone = (contact.get("phone") or "").strip()
			if not phone:
				problems.append(_("{0}: phone number missing").format(label))
			elif not phone.startswith("+"):
				problems.append(
					_("{0}: phone number {1} has to start with the country code, e.g. +49").format(
						label, frappe.bold(escape_html(phone))
					)
				)

		for idx, parcel in enumerate(parcels, start=1):
			if flt(parcel.get("weight")) <= 0:
				problems.append(_("Parcel {0}: weight missing").format(idx))

		if problems:
			frappe.throw(
				_("LetMeShip needs the following data:") + "<ul><li>" + "</li><li>".join(problems) + "</li></ul>",
				title=_("Missing Shipping Data"),
			)

	def get_parcel_hints(self, parcels):
		hints = []
		for idx, parcel in enumerate(parcels, start=1):
			if flt(parcel.get("weight")) > PARCEL_WEIGHT_LIMIT:
				hints.append(
					_(
						"Note: Parcel {0} weighs {1} kg. Most parcel services only carry up to {2} kg, so there may be no offer for it. Choose a pallet or freight transport type in the LetMeShip options."
					).format(idx, flt(parcel.get("weight")), PARCEL_WEIGHT_LIMIT)
				)

		return hints

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
		self.validate_request_data(pickup_address, delivery_address, pickup_contact, delivery_contact, parcels)
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
		except HTTPError as e:
			self.throw_request_error(e, parcels)
		except frappe.ValidationError:
			raise
		except Exception:
			show_error_alert("fetching LetMeShip prices")
			return []

		frappe.msgprint(
			"<br>".join([_("LetMeShip found no offers for this Shipment."), *self.get_parcel_hints(parcels)]),
			title=_("No Services Available"),
		)
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
		self.validate_request_data(pickup_address, delivery_address, pickup_contact, delivery_contact, parcels)
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
		except HTTPError as e:
			self.throw_request_error(e, parcels)
		except frappe.ValidationError:
			raise
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

		# documented as SUCCESSFUL / NOT_SUCCESSFUL, the API actually answers "successfully cancelled"
		if not (response_data.get("cancellationState") or "").lower().startswith("success"):
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

	def get_labels(self, shipment_id) -> list[bytes]:
		"""Return the PDF content of the shipping labels. Throws if none is ready yet."""
		try:
			response_data = self.request("GET", f"shipments/{shipment_id}/documents", params={"types": "LABEL"})
		except HTTPError as e:
			self.throw_request_error(e)

		documents = [d for d in response_data.get("documents") or [] if d.get("type", "LABEL") == "LABEL"]
		labels = [
			content
			for document in documents
			if (document.get("status") or "READY") == "READY" and (content := decode_document_data(document))
		]
		if not labels:
			states = ", ".join(document.get("status") or "?" for document in documents) or _("no document")
			frappe.throw(
				_(
					"The shipping label of Shipment {0} is not available yet (LetMeShip status: {1}). Please try again in a few minutes."
				).format(shipment_id, states),
				title=_("Shipping Label"),
			)

		return labels

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
				"pickupOrder": False,  # shipments are picked up on the pickup date anyway
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

		if options.transport_type:
			shipment_details["transportType"] = options.transport_type

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
			if self.settings.label_size and self.settings.label_size != "default":
				# the API rejects labelOptions as an object although documented like that
				payload["labelOptions"] = self.settings.label_size
			payload["labelEmail"] = True
		return payload

	def get_pickup_interval(self, pickup_date, options):
		pickup_interval = {"date": pickup_date}
		if options.pickup_from:
			pickup_interval["timeFrom"] = get_time(options.pickup_from).strftime("%H:%M:%S")
		if options.pickup_to:
			pickup_interval["timeTo"] = get_time(options.pickup_to).strftime("%H:%M:%S")

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
		available_service.cut_off_time = (response.get("cutOffTime") or "")[:5]
		available_service.transfer_time = response.get("transferTime") or ""
		available_service.unsuitable = any(
			UNSUITABLE_SERVICE_PATTERN.search(message) for message in available_service.messages
		)
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
		# some messages contain several lines separated by <br />
		lines = []
		for message in service.get("messages") or []:
			lines += re.split(r"<br\s*/?>", message or "", flags=re.IGNORECASE)

		return [line.strip() for line in lines if line.strip()]

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
		pickup_tail_lift=doc.get("letmeship_pickup_tail_lift"),
		delivery_tail_lift=doc.get("letmeship_delivery_tail_lift"),
		ddp=doc.get("incoterm") == "DDP",
		ex_works_type=EX_WORKS_TYPES.get(doc.get("letmeship_freight_payer")),
		ex_works_account=doc.get("letmeship_ex_works_account"),
		cash_on_delivery=flt(doc.get("letmeship_cod_amount")) if doc.get("letmeship_cash_on_delivery") else 0,
		pickup_from=doc.get("pickup_from"),
		pickup_to=doc.get("pickup_to"),
		transport_type=TRANSPORT_TYPES.get(doc.get("letmeship_transport_type")),
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


def get_error_message(response) -> str:
	"""Return LetMeShip's error text from a response or its JSON data."""
	data = response
	if isinstance(response, requests.Response):
		try:
			data = response.json()
		except ValueError:
			return (response.text or "").strip()[:500] or response.reason

	if isinstance(data, dict):
		if data.get("errorMessage"):
			return data["errorMessage"]

		messages = (data.get("status") or {}).get("message")
		if isinstance(messages, list):
			messages = "; ".join(message for message in messages if message)
		if messages:
			return messages

	return json_dumps(data)[:500]


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
