# utils/invoice_creation.py

import frappe
import json
from frappe.utils import flt, cint
from erpnext.selling.doctype.customer.customer import get_credit_limit, get_customer_outstanding

def get_pending_amount(shop_doc):
    
    territories = frappe.db.sql(
        """
        SELECT territory
        FROM `tabShop Territory`
        WHERE parent = %s
        """, (shop_doc.name), as_dict=1
    )
    # List comprehension to format territories
    formatted_territories = [t.territory for t in territories]
    
    # Join the list into a single string
    #territories_string = ", ".join(formatted_territories)
    
    sql_query = """
        select sum(g.debit-g.credit) as amount from `tabGL Entry` g Inner Join `tabCustomer` c on c.name = g.party
        where g.is_cancelled = 0 and c.territory IN (%s) and ((c.custom_customer_account_type  IS NULL) OR (c.custom_customer_account_type = 'NORMAL'))
    """
    placeholders = ','.join(['%s'] * len(formatted_territories))
    
    # Format the query with placeholders
    sql_query_formatted = sql_query % placeholders
    
    # Execute the SQL query with the territory_list as parameters
    pending = frappe.db.sql(sql_query_formatted, tuple(formatted_territories), as_dict=True)
    
    pending_amount = pending[0].amount if pending[0].amount else 0

    return pending_amount

def get_promotion(warehouse, item, customer, qty):
    #customer_group = frappe.db.get_value("Customer",customer, "customer_group")
    data = []

    campaign = None

    sql = """
            WITH cur AS (
            SELECT lft, rgt FROM `tabWarehouse` WHERE name = %(warehouse)s
            ),
            ancestors AS (  -- lignée: racine -> ... -> courant (inclus)
            SELECT w.name
            FROM `tabWarehouse` w
            JOIN cur ON w.lft <= cur.lft AND w.rgt >= cur.rgt
            )
            SELECT
                a.*,
                (%(qty)s DIV a.min_qty) * a.free_qty AS total_free_qty
            FROM (
                SELECT DISTINCT
                    ri.item_code,
                    r.name,
                    r.price_or_product_discount,
                    CASE WHEN COALESCE(r.same_item,0)=1 THEN ri.item_code ELSE r.free_item END AS free_item,
                    r.min_qty,
                    CASE WHEN r.price_or_product_discount = 'Product' THEN r.free_qty ELSE 0 END  AS free_qty,
                    CASE WHEN r.price_or_product_discount = 'Price'   THEN r.rate     ELSE 0 END  AS rate,
                    CASE WHEN COALESCE(r.max_qty,0) = 0 THEN 999999999999 ELSE r.max_qty END      AS max_qty
                FROM `tabPricing Rule` r
                INNER JOIN `tabPricing Rule Item Code` ri ON ri.parent = r.name
                INNER JOIN `tabCustomer` c ON c.name = %(customer)s
                WHERE
                    ri.item_code = %(item)s
                    AND COALESCE(r.disable,0) = 0
                    AND COALESCE(r.selling,0) = 1
                    AND (r.valid_from IS NULL OR CURDATE() >= r.valid_from)
                    AND (r.valid_upto IS NULL OR CURDATE() <= r.valid_upto)

                    -- 💡 Filtre "applicable_for"
                    AND (
                    COALESCE(r.applicable_for, '') = ''  -- Rien sélectionné : pas de contrainte
                    OR (
                        (r.applicable_for = 'Customer'       AND r.customer       =  c.name)
                        OR (r.applicable_for = 'Customer Group' AND r.customer_group =  c.customer_group)
                        OR (r.applicable_for = 'Territory'      AND r.territory       =  c.territory)
                        OR (r.applicable_for = 'Sales Partner'  AND r.sales_partner   =  c.default_sales_partner)
                        OR (r.applicable_for = 'Campaign'       AND r.campaign        =  %(campaign)s)
                    )
                    )

                    -- 🏭 Entrepôt optionnel : vide = pas de contrainte ; sinon doit être dans la lignée
                    AND (
                    r.warehouse IS NULL OR r.warehouse = ''
                    OR r.warehouse IN (SELECT name FROM ancestors)
                    )
            ) AS a
            WHERE %(qty)s BETWEEN a.min_qty AND a.max_qty
        """

    data = frappe.db.sql(sql, {
        "warehouse": warehouse,
        "item": item,
        "customer": customer,
        "qty": qty,
        "campaign": campaign
    }, as_dict=True)

    return data
    #else:
    #    return []
    
def get_item_batches(warehouse, item_code, promo_data, branch, max_qty, is_free_item = False, id=0, rate=0):
    """
    Get item batches based on the given parameters.

    Parameters:
    - warehouse (str): The warehouse code.
    - item_code (str): The item code.
    - promo_data (list): List of promotional data.
    - branch (str): The branch code.

    Returns:
    - list: List item batches.
    """

    batches =  frappe.db.sql(
        """
        SELECT sle.batch_no, SUM(sle.actual_qty) AS qty
        FROM `tabStock Ledger Entry` sle
        WHERE (sle.is_cancelled = 0) AND (sle.item_code = %(item_code)s) AND (sle.warehouse = %(warehouse)s) AND (sle.actual_qty <> 0)
        GROUP BY sle.batch_no
        HAVING SUM(sle.actual_qty) > 0
        """, {"warehouse": warehouse, "item_code": item_code}, as_dict = 1
    )

    return dispatch_by_batch(batches,promo_data, branch, item_code, max_qty, is_free_item, id, rate)




def dispatch_by_batch(batches,promo_data, branch, item_code, max_qty, is_free_item = False, id=0, rate=0):
    """
    Process and dispatch items based on batches and promotional data.

    Parameters:
    - batches (list): List of item batches.
    - promo_data (list): List of promotional data.
    - branch (str): The branch code.
    - item_code (str): The item code.
    - max_qty (float): The maximum quantity to be dispatched.
    - is_free_item (bool): Whether the item is a free item with a rate of 0.
    - id of order is negative and invoice is positive

    Returns:
    - list: List of invoice details.
    """

    invoice_details = []
    temp_batches = []
    for b in batches:
        t_batch = frappe._dict({"batch_no" : b.batch_no,"item_code":item_code, "qty": b.qty})
        temp_batches.append(t_batch)

    filtered_batches = [d for d in temp_batches if d["item_code"] == item_code and d["qty"] > 0]

    for b in filtered_batches:
        if not b.qty:
            continue
        if b.qty <= 0:
            continue

        while b.qty > 0 and max_qty > 0:
            if b.qty >= max_qty:
                details = frappe._dict({
                    "doctype": "Sales Invoice Item",
                    "item_code": item_code,
                    "qty": max_qty,
                    "batch_no": b.batch_no,
                    "branch": branch,
                })
                if int(id) < 0 :
                    details.update({"rate": rate})
                if len(promo_data) > 0:
                    if promo_data[0].price_or_product_discount == "Price":
                        details.update({"rate": promo_data[0].rate})
                if is_free_item :
                    details.update({
                        "rate": 0,
                        "price_list_rate": 0,
                    })
                invoice_details.append(details)
                b.qty -= max_qty
                max_qty = 0
                temp_batches[temp_batches.index(b)] = b
                break
            else:
                details = frappe._dict({
                    "doctype": "Sales Invoice Item",
                    "item_code": item_code,
                    "qty": b.qty,
                    "batch_no": b.batch_no,
                    "branch": branch,
                })
                if int(id) < 0 :
                    details.update({"rate": rate})
                if len(promo_data) > 0:
                    if promo_data[0].price_or_product_discount == "Price":
                        details.update({"rate": promo_data[0].rate})
                if is_free_item :
                    details.update({
                        "rate": 0,
                        "price_list_rate": 0,
                    })
                invoice_details.append(details)
                max_qty = max_qty - b.qty
                b.qty = 0
                temp_batches[temp_batches.index(b)] = b

    if max_qty > 0:
        details = frappe._dict({
            "doctype": "Sales Invoice Item",
            "item_code": item_code,
            "qty": max_qty,
            "branch": branch,
        })
        if int(id) < 0 :
            details.update({"rate": rate})
        if len(promo_data) > 0:
            if promo_data[0].price_or_product_discount == "Price":
                details.update({"rate": promo_data[0].rate})
        if is_free_item :
            details.update({
                "rate": 0,
                "price_list_rate": 0,
            })
        invoice_details.append(details)
    
    return invoice_details, filtered_batches

#///////////////////////////////////////////////////////////////////////////////////////////////
def parse_invoice_request(request_dict):
    return {
        "invoice_name": request_dict.get("invoice_name", "").strip(),
        "customer": request_dict.get("customer_name", "").strip(),
        "selling_price_list": request_dict.get("selling_price_list", "").strip(),
        "warehouse": request_dict.get("warehouse", "").strip(),
        "company": request_dict.get("customer_company", "").strip(),
        "branch": request_dict.get("customer_branch", "").strip(),
        "currency": request_dict.get("customer_currency", "").strip(),
        "sales_person": request_dict.get("customer_sales_person", "").strip(),
        "shop": request_dict.get("shop", "").strip(),
        "payment_type": request_dict.get("payment_type"),
        "total_amount": request_dict.get("total_amount"),
        "visit_name": request_dict.get("visit"),
        "is_order": cint(request_dict.get("is_order", 0)),
        "cart_data": request_dict.get("cart", []),
    }


def build_invoice_items(cart_data, warehouse, branch, customer, is_order=False):
    invoice_details = []
    cart_items = []
    temp_batches = []

    for i in cart_data:
        max_qty = i["quantity"]
        is_free = bool(i.get("is_free_item"))
        order_item_name = i.get("order_item_name")
        promo_data = [] if is_order else get_promotion(warehouse, i["product_code"], customer, max_qty)

        details, temp_batches = get_item_batches(
            warehouse, i["product_code"], promo_data, branch,
            max_qty, is_free, i["id"], i["price"]
        )

        if is_order:
            for d in details:
                d["sales_order"] = i["order_id"]
                d["so_detail"] = i["order_item_id"]
                
        invoice_details.extend(details)

        if not is_order and promo_data:
            for p in promo_data:
                if p["price_or_product_discount"] == "Product" and p["total_free_qty"] > 0:
                    if i["product_code"] == p["free_item"]:
                        extra_details, _ = dispatch_by_batch(temp_batches, [], branch, p["free_item"], p["total_free_qty"], True, i["id"], 0)
                        invoice_details.extend(extra_details)
                    else:
                        extra_details, temp_batches = get_item_batches(warehouse, p["free_item"], [], branch, p["total_free_qty"], True, i["id"], 0)
                        invoice_details.extend(extra_details)

        if order_item_name:
            cart_items.append({
                "name": order_item_name,
                "billed_amt": i["amount"],
                "delivered_qty": i["quantity"]
            })



    #frappe.throw(json.dumps(invoice_details, indent=2))

    return invoice_details, cart_items


def generate_sales_invoice(args):
    sale = frappe.get_doc(args)
    sale.ignore_pricing_rule = 1
    sale.insert()
    return sale


def update_sales_order_items(cart_items):
    for i in cart_items:
        try:
            if i.get("name"):
                frappe.db.set_value("Sales Order Item", i["name"], "billed_amt", flt(i["billed_amt"]))
                frappe.db.set_value("Sales Order Item", i["name"], "delivered_qty", flt(i["delivered_qty"]))
        except Exception as e:
            frappe.log_error(f"Failed to update order item {i['name']}: {str(e)}", "Sales Order Update Error")


def validate_credit_limit(customer, company, shop_doc, total_amount):
    pending_amount = get_pending_amount(shop_doc)
    meta = frappe.get_meta("Customer")
    custom_type = frappe.db.get_value("Customer", customer, "custom_customer_account_type")

    if meta.get_field("custom_customer_account_type") and custom_type != "CONTRACT CUSTOMER":
        if not shop_doc.unlimited_credit:
            total_pending = flt(pending_amount) + flt(total_amount) * 0.15
            if flt(shop_doc.credit_limit) < total_pending:
                frappe.throw(f"Your pending is {total_pending} which is more than your credit limit {shop_doc.credit_limit}. You cannot credit this customer!")

    outstanding_amt = get_customer_outstanding(customer, company, ignore_outstanding_sales_order=True)
    credit_limit = get_credit_limit(customer, company)
    total_out = flt(outstanding_amt) + flt(total_amount) * 0.15
    if flt(credit_limit) < total_out:
        frappe.throw(f"Credit limit is {credit_limit}, but outstanding amount is {total_out}. Cannot create more invoices!")



