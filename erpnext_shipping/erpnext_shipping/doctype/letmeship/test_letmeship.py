# Copyright (c) 2020, Frappe and Contributors
# See license.txt

import unittest

import frappe

from erpnext_shipping.erpnext_shipping.doctype.letmeship.letmeship import (
	LetMeShipUtils,
	decode_document_data,
	parse_amount,
)


class TestLetMeShip(unittest.TestCase):
	def setUp(self):
		self.utils = LetMeShipUtils(base_url="", api_id="", api_password="")

	def test_parse_amount(self):
		self.assertEqual(parse_amount("520.00"), 520)
		self.assertEqual(parse_amount("520.00."), 520)
		self.assertEqual(parse_amount("1.000"), 1000)
		self.assertEqual(parse_amount("1.000,50"), 1000.5)
		self.assertEqual(parse_amount("1,000.50"), 1000.5)
		self.assertEqual(parse_amount("99,5"), 99.5)

	def test_insurance_limit(self):
		messages = ["Shipment can be insured up to 520.00 €."]
		self.assertEqual(self.utils.get_insurance_limit(messages), 520)
		self.assertIsNone(self.utils.get_insurance_limit(["Some other message"]))

	def test_insurance_premium(self):
		price_info = {
			"surcharges": [{"name": "Insurance", "amount": 2.5}, {"name": "Fuel", "amount": 1}],
			"specialSurcharges": None,
		}
		self.assertEqual(self.utils.get_insurance_premium(price_info), 2.5)
		self.assertEqual(self.utils.get_insurance_premium({"surcharges": []}), 0)

	def test_service_dict_insurance_limit(self):
		response = {
			"baseServiceDetails": {
				"id": 1,
				"name": "Express",
				"carrier": "DHL",
				"priceInfo": {"realWeight": 1, "netPrice": 10, "surcharges": []},
			},
			"messages": ["Shipment can be insured up to 520.00 €.\r\n"],
			"isEoriRequired": True,
		}
		service = self.utils.get_service_dict(response, frappe._dict(insurance=1), 1000)
		self.assertEqual(service.insurance_limit, 520)
		self.assertEqual(service.messages, ["Shipment can be insured up to 520.00 €."])
		self.assertEqual(len(service.customs_requirements), 1)

		service = self.utils.get_service_dict(response, frappe._dict(insurance=1), 500)
		self.assertIsNone(service.insurance_limit)

	def test_cash_on_delivery_on_first_parcel(self):
		parcels = [
			{"count": 1, "length": 10, "width": 10, "height": 10, "weight": 1},
			{"count": 2, "length": 10, "width": 10, "height": 10, "weight": 1},
		]
		parcel_list = self.utils.get_parcel_list(parcels, "Goods", 49.9)
		self.assertEqual(parcel_list[0]["cashOnDelivery"]["value"], 49.9)
		self.assertNotIn("cashOnDelivery", parcel_list[1])

	def test_decode_document_data(self):
		self.assertEqual(decode_document_data({"data": [37, 80, 68, 70]}), b"%PDF")
		self.assertEqual(decode_document_data({"dataEncoded": "JVBERg=="}), b"%PDF")
		self.assertIsNone(decode_document_data({}))
