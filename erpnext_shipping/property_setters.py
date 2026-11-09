def get_property_setters():
	return [
		# derived from the LetMeShip transport type, see shipping.set_pallets
		("Shipment", "pallets", "read_only", 1),
		("Shipment", "pallets", "allow_on_submit", 1),
		# ("Address", "state", "hidden", 1),
		# ("Address", None, "track_changes", 1),
	]
