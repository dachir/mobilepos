// Copyright (c) 2024, Kossivi Amouzou and contributors
// For license information, please see license.txt

frappe.ui.form.on('Shop', {
	before_load: function (frm) {
		var update_tz_select = function (user_language) {
			frm.set_df_property("time_zone", "options", [""].concat(frappe.all_timezones));
		};

		if (!frappe.all_timezones) {
			frappe.call({
				method: "frappe.core.doctype.user.user.get_timezones",
				callback: function (r) {
					frappe.all_timezones = r.message.timezones;
					update_tz_select();
				},
			});
		} else {
			update_tz_select();
		}
	},

	time_zone: function (frm) {
		if (frm.doc.time_zone && frm.doc.time_zone.startsWith("Etc")) {
			frm.set_df_property(
				"time_zone",
				"description",
				__("Note: Etc timezones have their signs reversed.")
			);
		}
	},

	use_shop_price_list: function(frm) {
		if (frm.doc.use_shop_price_list == 0){
			frm.set_value('shop_price_list', "");
			frm.set_df_property('shop_price_list', 'reqd', 0);
		}
		else{
			rm.set_df_property('shop_price_list', 'reqd', 1);
		}
	},
	// refresh: function(frm) {

	// }
});
