import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from mobilepos.mobile_pos import create_pos_cash_invoice_payment, process_cart_data
from zatca2024.zatca2024.zatcasdkcode import zatca_Background_on_submit

class CustomSalesInvoice(SalesInvoice):
    def on_submit(self):
        if self.shop:
            items = frappe.db.sql(
                """
                SELECT item, SUM(qty) AS quantite
                FROM `tabSales Invoice Item`
                WHERE parent = %s
                """, (self.name), as_dict=1
            )

            invoice_details = process_cart_data(items, self.set_warehouse, self.branch, self.customer)
            self.items.clear()
            for i in invoice_details :
                self.append('items', i)

        zatca_Background_on_submit(doc)

    def after_submit(self):
        frappe.throw("test")
        if self.shop:
            if self.payment_type == "Cash":
                    visit =  frappe.db.sql(
                        """
                        SELECT parent as name
                        FROM `tabShop Visit Details` 
                        WHERE document_name = %s
                        """, (self.name), as_dict = 1
                    )
                    if visit:
                        create_pos_cash_invoice_payment(self.shop, self.company, self.customer, self.name, self.branch, self.grand_total, visit[0].name)


def test():
    frappe.throw("test")
                        