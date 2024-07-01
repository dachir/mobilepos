# Copyright (c) 2024, Kossivi Amouzou and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class Shop(Document):
	def before_save(self):
		self.get_items()

	def before_insert(self):
		self.get_items()

	def get_items(self):
		items = frappe.db.sql(
			"""
			SELECT i.name, i.item_group, i.item_name, p.price_list_rate, 0 AS quantity, i.image
			FROM tabShop s CROSS JOIN tabItem i INNER JOIN `tabItem Price` p ON p.price_list = s.shop_price_list AND p.item_code = i.name
			LEFT JOIN `tabShop Item` si ON si.item_code = i.name AND si.parent = s.name
			WHERE si.item_code IS NULL AND i.item_group = 'Finished Goods' AND s.name = %s 
			""",(self.name), as_dict=1
		)

		for i in items:
			item_liste = frappe.db.sql(
				"""
				SELECT actual_qty
				FROM tabBin 
				WHERE item_code = %s AND warehouse = %s
				""",(i.name, self.warehouse), as_dict=1
			)
			qty = 0
			if len (item_liste) > 0 :
				qty = item_liste[0]
				
			self.append('shop_items',{
					"item_code": i.name,
					"item_name": i.item_name,
					"item_group": i.item_group,
					"image": i.image,
					"quantity": qty,
					"rate": i.price_list_rate,
					"status": 0,
				}
			)


	def get_item_qty(self):
		items = frappe.db.sql(
			"""
			SELECT b.actual_qty, si.item_code, si.name
			FROM tabBin 
			WHERE item_code = %s AND warehouse = %s
			""",(self.name), as_dict=1
		)

	def update_items(self):
		self.update_quantity()
		self.update_price()

	def update_quantity(self):
		items = frappe.db.sql(
			"""
			SELECT b.actual_qty, si.item_code, si.name
			FROM tabShop s INNER JOIN  `tabShop Item`si ON si.parent = s.name 
				INNER JOIN tabBin b ON si.item_code = b.item_code AND s.warehouse = b.warehouse 
			WHERE s.name = %s 
			""",(self.name), as_dict=1
		)

		for i in items:
			frappe.db.set_value('Shop Item', i.name, {'quantity': i.actual_qty, 'status': 0})

	def update_price(self):
		items = frappe.db.sql(
			"""
			SELECT si.name, si.item_code, p.price_list_rate
			FROM tabShop s INNER JOIN  `tabShop Item`si ON si.parent = s.name INNER JOIN `tabItem Price` p 
				ON p.price_list = s.shop_price_list AND p.item_code = si.item_code
			WHERE s.name = %s 
			""",(self.name), as_dict=1
		)

		for i in items:
			frappe.db.set_value('Shop Item', i.name, {'rate': i.price_list_rate, 'status': 0})
	
