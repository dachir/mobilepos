import frappe

def all():
    pass

def cron():
    liste = frappe.db.get_list("Shop",["name"])
    for i in liste:
        shop = frappe.get_doc("Shop", i.name)
        shop.update_items()

def hourly():
    pass
def daily():
    pass


def weekly():
    pass
def monthly():
    pass

