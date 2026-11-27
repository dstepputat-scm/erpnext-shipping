from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from .custom_fields import get_custom_fields
from .erpnext_shipping.patches import set_letmeship_defaults
from .property_setters import get_property_setters
from .utils import make_property_setters


def after_install():
	create_custom_fields(get_custom_fields())
	make_property_setters(get_property_setters())
	# only fills missing values, so re-running after_install keeps the user's settings
	set_letmeship_defaults.execute()
