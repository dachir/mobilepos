import frappe

@frappe.whitelist(allow_guest=True)
def get_categories(shop, limit=10, offset=1):
    data = frappe.db.get_all("Shop Item Category", ["*"], filters={"shop":shop}, limit=limit,limit_start=offset)
    return frappe._dict({
        "total": data.length,
        "limit": limit,
        "offset": offset,
        "categories": data,
    })