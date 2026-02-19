import re
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

# ---------------------------
# Helpers
# ---------------------------

def only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def get_latest_app_reg_log(email: str):
    # Adjust doctype + fieldnames
    return frappe.get_all(
        "App Registration Log",
        filters={"email": email},
        fields=["*"],
        order_by="creation desc",
        limit=1
    )

def ensure_user(email: str, phone_digits: str) -> str:
    if frappe.db.exists("User", email):
        return email

    user = frappe.get_doc({
        "doctype": "User",
        "email": email,
        "first_name": phone_digits,
        "enabled": 1,
        # If you want to force username = digits, you can set "username" in some setups,
        # but in ERPNext typically email is the name/identifier.
        # "username": phone_digits,
        "send_welcome_email": 0
    })
    user.insert(ignore_permissions=True)

    # Optionally set a password (internal-only)
    # frappe.utils.password.set_password(user.name, "@barHa1lWater")
    return user.name

def ensure_customer(email: str, phone_digits: str) -> str:
    # Strategy: find customer by email field if you store it,
    # or by naming convention, or via Dynamic Link from Contact.
    # Minimal reliable: store customer_code in App Registration Log when you create it,
    # and here we try to find by that first.

    # Try find by a custom field if you have e.g. customer_email
    if frappe.db.has_column("Customer", "email_id"):
        existing = frappe.db.get_value("Customer", {"email_id": email}, "name")
        if existing:
            return existing

    # Fallback: create new customer
    cust = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": phone_digits,
        "customer_type": "Individual",
        # If you have fields:
        # "email_id": email,
        # "mobile_no": phone_digits,
        "customer_group": "Individual",
        "territory": "All Territories",
    })
    cust.insert(ignore_permissions=True)
    return cust.name

def ensure_address(customer: str, phone_digits: str, lat=None, lon=None) -> str:
    # Default lat/lon to 0 if missing, as requested
    lat = 0 if lat in (None, "",) else lat
    lon = 0 if lon in (None, "",) else lon

    # If you use naming convention customer_01 etc, try to locate an existing one:
    existing = frappe.get_all(
        "Address",
        filters=[
            ["Dynamic Link", "link_doctype", "=", "Customer"],
            ["Dynamic Link", "link_name", "=", customer],
        ],
        fields=["name"],
        limit=1
    )
    if existing:
        return existing[0]["name"]

    addr = frappe.get_doc({
        "doctype": "Address",
        "address_title": phone_digits,
        "address_type": "Billing",
        "address_line1": phone_digits,  # minimal placeholder
        "city": "",
        "state": "",
        "country": "",
        "pincode": "",
        "phone": phone_digits,
        # Custom fields if you have:
        "custom_latitude": lat,
        "custom_longitude": lon,
        "links": [{"link_doctype": "Customer", "link_name": customer}],
    })
    addr.insert(ignore_permissions=True)
    return addr.name

def mark_app_reg_log(email: str, status: str, customer_code: str = None, details: str = None):
    # update latest log or create one
    latest = get_latest_app_reg_log(email)
    if latest:
        doc = frappe.get_doc("App Registration Log", latest[0]["name"])
        doc.status = status
        if customer_code:
            doc.customer_code = customer_code
        if details and hasattr(doc, "details"):
            doc.details = details
        doc.save(ignore_permissions=True)
        return doc.name

    doc = frappe.get_doc({
        "doctype": "App Registration Log",
        "user_email": email,
        "status": status,
        "customer_code": customer_code,
        "details": details
    })
    doc.insert(ignore_permissions=True)
    return doc.name

def is_complete(email: str):
    user_exists = frappe.db.exists("User", email)

    # customer resolution is project-dependent; simplest is via App Registration Log
    latest = get_latest_app_reg_log(email)
    customer = latest[0].get("customer_code") if latest else None
    if customer and not frappe.db.exists("Customer", customer):
        customer = None

    if not customer:
        # Try a guess if you store Customer.email_id
        if frappe.db.has_column("Customer", "email_id"):
            customer = frappe.db.get_value("Customer", {"email_id": email}, "name")

    if not customer:
        return False, None, None

    # address exists?
    addr = frappe.get_all(
        "Address",
        filters=[
            ["Dynamic Link", "link_doctype", "=", "Customer"],
            ["Dynamic Link", "link_name", "=", customer],
        ],
        fields=["name"],
        limit=1
    )
    address = addr[0]["name"] if addr else None

    return bool(user_exists and customer and address), customer, address