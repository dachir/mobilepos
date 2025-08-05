import frappe
from mobile_pos import get_branch_name_by_location


def create_order(doc, method):
    if doc.customer.startswith("AC"):
        add_doc = frappe.get_doc("Address",doc.customer_address)
        branch = get_branch_name_by_location(add_doc.latitude, add_doc.longitude)
        if branch:
            doc.branch = branch
        else:
            frappe.throw("We are not serving in this area!")