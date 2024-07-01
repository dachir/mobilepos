import frappe
from erpnext.stock.doctype.item_price.item_price import ItemPrice

class CustomItemPrice(ItemPrice):
    def before_insert(self):
        self.update_shops_item()

    def before_save(self):
        self.update_shops_item()

    def update_shops_item(self):
        liste = frappe.db.sql(
            """
            SELECT ip.price_list, ip.item_code, ip.price_list_rate, IFNULL(b.actual_qty, 0) AS quantity, 
                i.item_group, i.item_name, i.image, s.name AS shop, si.name AS shop_item_id
            FROM `tabItem Price` ip INNER JOIN tabShop s ON s.shop_price_list = ip.price_list LEFT JOIN tabBin b
                ON ip.item_code = b.item_code AND s.warehouse = b.warehouse INNER JOIN tabItem i ON i.name = ip.item_code
                LEFT JOIN `tabShop Item` si ON si.item_code = i.name AND si.parent = s.name
            WHERE ip.selling = 1 AND i.item_group = 'Finished Goods' AND ip.item_code = %s
            """, (self.item_code), as_dict=1
        )

        for i in liste:
            #insertion
            shop = frappe.get_doc("Shop", i.shop)
            shop.save()

            #Update
            frappe.db.set_value('Shop Item', i.shop_item_id, 
            {
                "item_code": i.item_code,
                "item_name": i.item_name,
                "item_group": i.item_group,
                "image": i.image,
                "quantity": i.quantity,
                "rate": self.price_list_rate,
                "status": 0,
            })
            frappe.db.commit()
            
