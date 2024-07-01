import frappe
from erpnext.stock.doctype.stock_ledger_entry.stock_ledger_entry import StockLedgerEntry

class CustomStockLedgerEntry(StockLedgerEntry):

    def before_save(self):
        pass

    def update_quantity(self):
        liste = frappe.db.sql(
            """
            SELECT ip.price_list, ip.item_code, ip.price_list_rate, ABS(sle.qty_after_transaction) AS quantity, 
                i.item_group, i.item_name, i.image, s.name AS shop, si.name AS shop_item_id
            FROM `tabStock Ledger Entry` sle INNER JOIN tabItem i  ON i.name = sle.item_code INNER JOIN tabShop s ON s.warehouse = sle.warehouse
                INNER JOIN `tabShop Item` si ON si.item_code = i.name AND si.parent = s.name
                INNER JOIN `tabItem Price` ip ON s.shop_price_list = ip.price_list AND ip.item_code = i.name
            WHERE i.item_group = 'Finished Goods' AND si.item_code = %s AND sle.name = %s
            """, (self.item_code, self.name)
        )

        for i in liste:
            frappe.db.set_value('Shop Item', i.shop_item_id, 
            {
                "quantity": i.quantity,
                "status": 0,
            })
            frappe.db.commit()