// Copyright (c) 2020, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Shipment", {
	refresh: function (frm) {
		if (frm.doc.docstatus === 1 && !frm.doc.shipment_id) {
			frm.add_custom_button(__("Fetch Shipping Rates"), function () {
				if (frm.doc.shipment_parcel.length > 1) {
					frappe.confirm(
						__(
							"If your shipment contains packages with varying weights, the estimated shipping rates may differ from the final price charged by your carrier. Do you wish to proceed?",
						),
						function () {
							frm.events.fetch_shipping_rates(frm);
						},
					);
				} else {
					frm.events.fetch_shipping_rates(frm);
				}
			});
		}
		if (frm.doc.shipment_id) {
			frm.add_custom_button(
				__("Print Shipping Label"),
				function () {
					return frm.events.print_shipping_label(frm);
				},
				__("Tools"),
			);
			if (frm.doc.service_provider == "LetMeShip" && frm.doc.tracking_status == "Delivered") {
				frm.add_custom_button(
					__("Proof of Delivery"),
					function () {
						return frm.events.fetch_proof_of_delivery(frm);
					},
					__("Tools"),
				);
			}
			if (frm.doc.tracking_status != "Delivered") {
				frm.add_custom_button(
					__("Update Tracking"),
					function () {
						return frm.events.update_tracking(frm, frm.doc.service_provider, frm.doc.shipment_id);
					},
					__("Tools"),
				);

				frm.add_custom_button(
					__("Track Status"),
					function () {
						if (frm.doc.tracking_url) {
							const urls = frm.doc.tracking_url.split(", ");
							urls.forEach((url) => window.open(url));
						} else {
							let msg = __("Please complete Shipment (ID: {0}) on {1} and Update Tracking.", [
								frm.doc.shipment_id,
								frm.doc.service_provider,
							]);
							frappe.msgprint({ message: msg, title: __("Incomplete Shipment") });
						}
					},
					__("View"),
				);
			}
		}
	},

	value_from_sales_order: function (frm) {
		get_from_sales_order(frm, "value_of_goods");
	},

	description_from_sales_order: function (frm) {
		get_from_sales_order(frm, "description_of_content");
	},

	fetch_shipping_rates: function (frm) {
		if (!frm.doc.shipment_id) {
			if (frm.is_dirty()) {
				// the rates depend on the shipping options, which are read from the saved Shipment
				frm.save("Update").then(() => frm.events.fetch_shipping_rates(frm));
				return;
			}

			frappe.call({
				method: "erpnext_shipping.erpnext_shipping.shipping.fetch_shipping_rates",
				freeze: true,
				freeze_message: __("Fetching Shipping Rates"),
				args: {
					pickup_from_type: frm.doc.pickup_from_type,
					delivery_to_type: frm.doc.delivery_to_type,
					pickup_address_name: frm.doc.pickup_address_name,
					delivery_address_name: frm.doc.delivery_address_name,
					parcels: frm.doc.shipment_parcel,
					description_of_content: frm.doc.description_of_content,
					pickup_date: frm.doc.pickup_date,
					pickup_contact_name:
						frm.doc.pickup_from_type === "Company"
							? frm.doc.pickup_contact_person
							: frm.doc.pickup_contact_name,
					delivery_contact_name: frm.doc.delivery_contact_name,
					value_of_goods: frm.doc.value_of_goods,
					shipment: frm.doc.name,
				},
				callback: function (r) {
					if (r.message && r.message.length) {
						select_from_available_services(frm, r.message);
					} else if (!r._server_messages) {
						// the server already explains why there are no services
						frappe.msgprint({
							message: __("No Shipment Services available"),
							title: __("Note"),
						});
					}
				},
			});
		} else {
			frappe.throw(__("Shipment already created"));
		}
	},

	print_shipping_label: function (frm) {
		frappe.call({
			method: "erpnext_shipping.erpnext_shipping.shipping.print_shipping_label",
			freeze: true,
			freeze_message: __("Printing Shipping Label"),
			args: {
				shipment: frm.doc.name,
			},
			callback: function (r) {
				if (r.message) {
					const urls = Array.isArray(r.message) ? r.message : [r.message];
					const blocked = urls.filter((url) => !window.open(url));
					if (blocked.length) {
						// the browser blocked the new tab, offer the links instead
						frappe.msgprint({
							title: __("Shipping Label"),
							message: blocked
								.map((url) => `<a href="${encodeURI(url)}" target="_blank">${__("Open Shipping Label")}</a>`)
								.join("<br>"),
						});
					}
					frm.reload_doc();
				}
			},
		});
	},

	fetch_proof_of_delivery: function (frm) {
		frappe.call({
			method: "erpnext_shipping.erpnext_shipping.shipping.fetch_proof_of_delivery",
			freeze: true,
			freeze_message: __("Fetching Proof of Delivery"),
			args: {
				shipment: frm.doc.name,
			},
			callback: function (r) {
				if (r.message) {
					window.open(r.message);
					frm.reload_doc();
				}
			},
		});
	},

	update_tracking: function (frm, service_provider, shipment_id) {
		const delivery_notes = frm.doc.shipment_delivery_note.map((d) => d.delivery_note);

		frappe.call({
			method: "erpnext_shipping.erpnext_shipping.shipping.update_tracking",
			freeze: true,
			freeze_message: __("Updating Tracking"),
			args: {
				shipment: frm.doc.name,
				shipment_id: shipment_id,
				service_provider: service_provider,
				delivery_notes: delivery_notes,
			},
			callback: function (r) {
				if (!r.exc) {
					frm.reload_doc();
				}
			},
		});
	},
});

async function get_from_sales_order(frm, fieldname) {
	if (!frm.doc.__sales_order) {
		// suggest the Sales Order of the linked Delivery Notes
		const delivery_notes = (frm.doc.shipment_delivery_note || [])
			.map((d) => d.delivery_note)
			.filter(Boolean);
		const r = await frappe.call({
			method: "erpnext_shipping.erpnext_shipping.shipping.get_sales_orders_of_delivery_notes",
			args: { delivery_notes: delivery_notes },
		});
		frm.doc.__sales_order = (r.message || [])[0];
	}

	const customer = frm.doc.delivery_to_type === "Customer" ? frm.doc.delivery_customer : null;
	const dialog = new frappe.ui.Dialog({
		title: __("Select Sales Order"),
		fields: [
			{
				fieldtype: "Link",
				fieldname: "sales_order",
				label: __("Sales Order"),
				options: "Sales Order",
				reqd: 1,
				default: frm.doc.__sales_order,
				description: customer ? __("Sales Orders of {0}", [customer]) : "",
				get_query: () => ({
					filters: Object.assign({ docstatus: 1 }, customer ? { customer: customer } : {}),
				}),
			},
		],
		primary_action_label: __("Apply"),
		primary_action: async (values) => {
			const r = await frappe.call({
				method: "erpnext_shipping.erpnext_shipping.shipping.get_sales_order_details",
				args: { sales_order: values.sales_order },
			});
			frm.doc.__sales_order = values.sales_order;
			frm.set_value(fieldname, r.message[fieldname]);
			dialog.hide();
		},
	});
	dialog.show();
}

function select_from_available_services(frm, available_services) {
	frappe.require("shipping.bundle.js", () => show_service_selector(frm, available_services));
}

function get_service_notes(service) {
	const notes = [];
	if (service.insurance) {
		notes.push(
			service.insurance_premium
				? __("Insurance: {0}", [format_currency(service.insurance_premium, service.currency, 2)])
				: __("Insurance included"),
		);
	}
	if (service.insurance_limit) {
		notes.push(
			`<span class="text-warning">${__("Only insured up to {0}", [
				format_currency(service.insurance_limit, service.currency, 2),
			])}</span>`,
		);
	}
	if (service.customs_requirements && service.customs_requirements.length) {
		notes.push(
			`<span class="text-warning">${__("Requires: {0}", [
				frappe.utils.escape_html(service.customs_requirements.join(", ")),
			])}</span>`,
		);
	}
	(service.messages || []).forEach((message) => {
		// highlight the messages that make a service unsuitable
		const css_class = /exceeded|not possible|(doesn't|does not) support|please enter/i.test(message)
			? "text-danger"
			: "text-muted";
		notes.push(`<span class="${css_class}">${frappe.utils.escape_html(message)}</span>`);
	});
	return notes.join("<br>");
}

function show_service_selector(frm, available_services) {
	const arranged_services = available_services.reduce(
		(prev, curr) => {
			curr.notes = get_service_notes(curr);
			if (curr.unsuitable) {
				prev.unsuitable_services.push(curr);
			} else if (curr.is_preferred) {
				prev.preferred_services.push(curr);
			} else {
				prev.other_services.push(curr);
			}
			return prev;
		},
		{ preferred_services: [], other_services: [], unsuitable_services: [] },
	);

	const sections = [
		{
			key: "preferred_services",
			title: __("Preferred Services"),
			empty_message: __("No Preferred Services Available"),
		},
		{
			key: "other_services",
			title: __("Other Services"),
			empty_message: __("No Services Available"),
		},
		{
			key: "unsuitable_services",
			title: __("Unsuitable Services"),
			description: __(
				"The carrier reports that the Shipment exceeds a limit of these services or an option is not supported. Booking them may fail or cost extra.",
			),
			collapsible: true,
			hide_if_empty: true,
		},
	].map((section) => Object.assign(section, { services: arranged_services[section.key] }));

	const dialog = new frappe.ui.Dialog({
		title: __("Select Service to Create Shipment"),
		size: "extra-large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "available_services",
				label: __("Available Services"),
			},
		],
	});
	// use the available screen width, the notes column needs room
	dialog.$wrapper.find(".modal-dialog").css({ "max-width": "min(1600px, 96vw)", width: "auto" });

	const delivery_notes = frm.doc.shipment_delivery_note.map((d) => d.delivery_note);

	dialog.fields_dict.available_services.$wrapper.html(
		frappe.render_template("shipment_service_selector", {
			has_services: available_services.length > 0,
			show_provider: new Set(available_services.map((s) => s.service_provider)).size > 1,
			sections: sections,
		}),
	);

	dialog.$body.on("click", "button[data-type]", function () {
		const service_type = $(this).attr("data-type");
		const service_index = cint($(this).attr("data-index"));
		frm.select_row(arranged_services[service_type][service_index]);
	});

	frm.select_row = function (service_data) {
		frappe.call({
			method: "erpnext_shipping.erpnext_shipping.shipping.create_shipment",
			freeze: true,
			freeze_message: __("Creating Shipment"),
			args: {
				shipment: frm.doc.name,
				pickup_from_type: frm.doc.pickup_from_type,
				delivery_to_type: frm.doc.delivery_to_type,
				pickup_address_name: frm.doc.pickup_address_name,
				delivery_address_name: frm.doc.delivery_address_name,
				shipment_parcel: frm.doc.shipment_parcel,
				description_of_content: frm.doc.description_of_content,
				pickup_date: frm.doc.pickup_date,
				pickup_contact_name:
					frm.doc.pickup_from_type === "Company"
						? frm.doc.pickup_contact_person
						: frm.doc.pickup_contact_name,
				delivery_contact_name: frm.doc.delivery_contact_name,
				value_of_goods: frm.doc.value_of_goods,
				service_data: service_data,
				delivery_notes: delivery_notes,
			},
			callback: function (r) {
				if (!r.exc) {
					frm.reload_doc();
					frappe.msgprint({
						message: __("Shipment {1} has been created with {0}.", [
							r.message.service_provider,
							String(r.message.shipment_id).bold(),
						]),
						title: __("Shipment Created"),
						indicator: "green",
					});
					frm.events.update_tracking(frm, r.message.service_provider, r.message.shipment_id);
				}
			},
		});
		dialog.hide();
	};
	dialog.show();
}
