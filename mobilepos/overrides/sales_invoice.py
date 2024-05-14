import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from mobilepos.mobile_pos import create_pos_cash_invoice_payment, process_cart_data
from zatca2024.zatca2024.zatcasdkcode import zatca_Background_on_submit

class CustomSalesInvoice(SalesInvoice):
    @frappe.whitelist()
    def recalculate_batch(self):
        process_cart_data(self)
