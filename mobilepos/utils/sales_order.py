import frappe
from mobilepos.mobile_pos import get_branch_name_by_location, normalize_ksa_coordinates
#from shapely.geometry import Point


def create_order(doc, method):
    if doc.customer.startswith("AC"):
        add_doc = frappe.get_doc("Address",doc.customer_address)
        #location = Point(add_doc.custom_longitude or doc.custom_longitude, add_doc.custom_latitude or doc.custom_latitude)
        #lat, lon, swapped, reason = normalize_ksa_coordinates(add_doc.custom_latitude or doc.custom_latitude, add_doc.custom_longitude or doc.custom_longitude)

        lat, lon, swapped = normalize_ksa_coordinates(add_doc.custom_latitude or doc.custom_latitude, add_doc.custom_longitude or doc.custom_longitude, strict=False)

        if swapped:
            frappe.log_error(f"GEO_DEBUG lat={lat} lon={lon} swapped={swapped}", "Coordinate Normalization")

        branch = get_branch_name_by_location(lat, lon)
        if branch:
            doc.branch = branch
            doc.territory = branch
            pl_name = frappe.db.get_value('Price List', { "custom_branch": branch, "custom_is_mobile_price_list": 1 }, 'name')
            if pl_name:
                doc.selling_price_list =  pl_name
            else:
                frappe.throw("No Price List for this branch regarding this customer!")
        else:
            frappe.throw("We are not serving in this area!")
            