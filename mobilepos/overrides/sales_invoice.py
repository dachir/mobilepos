from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from mobilepos.mobile_pos import create_pos_cash_invoice_payment

class CustomSalesInvoice(SalesInvoice):
    def on_submit(self):
        frappe.msgprint("shop: " + self.shop)
        frappe.msgprint(" company:" + self.company)
        frappe.msgprint(" customer:" + self.customer)
        frappe.msgprint( "name:" + self.name )
        frappe.msgprint( " grand_total:" + str(self.grand_total) )
        frappe.msgprint(  " payment_type:" + self.payment_type)
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
                        frappe.msgprint(" visit:" + visit[0].name)
                        create_pos_cash_invoice_payment(self.shop, self.company, self.customer, self.name, self.branch, self.grand_total, visit[0].name)
                        