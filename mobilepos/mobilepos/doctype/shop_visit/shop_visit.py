# Copyright (c) 2024, Kossivi Amouzou and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class ShopVisit(Document):
	
	def on_submit(self):
		customer_doc = frappe.get_doc("Customer", self.customer)
		customer_doc.last_visit = self.begin
		customer_doc.save()
