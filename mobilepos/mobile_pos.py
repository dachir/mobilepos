import frappe
from frappe import _
from frappe.utils import flt, getdate, get_time
from datetime import datetime,timedelta
from frappe.core.doctype.user.user import get_timezones
from erpnext.setup.utils import get_exchange_rate
from erpnext.selling.doctype.customer.customer import get_credit_limit, get_customer_outstanding
from frappe.model.meta import get_meta
from erpnext.stock.doctype.batch.batch import UnableToSelectBatchError

import json

def get_balance(customer, company):
    outstanding_amt = get_customer_outstanding(
        customer, company, ignore_outstanding_sales_order=i.bypass_credit_limit_check
    )
    credit_limit = get_credit_limit(customer, company)

    return flt(credit_limit) - flt(outstanding_amt)

def get_promotion(warehouse, item, customer_group, qty):
    data = []

    data = frappe.db.sql(
        """
        SELECT *, (%(qty)s DIV a.min_qty) * a.free_qty AS total_free_qty
        FROM(
            SELECT DISTINCT ri.item_code, r.name,r.price_or_product_discount,
                CASE WHEN r.same_item THEN ri.item_code ELSE r.free_item END as free_item,
                min_qty,
                CASE WHEN r.price_or_product_discount = 'Product' THEN free_qty ELSE 0 END  as free_qty, 
                CASE WHEN r.price_or_product_discount = 'Price' THEN  rate ELSE 0 END as rate,
                CASE WHEN max_qty = 0 THEN 999999999999 ELSE max_qty END as max_qty
            FROM `tabPricing Rule` r INNER JOIN `tabPricing Rule Item Code` ri ON ri.parent = r.name
                INNER JOIN (SELECT w.name
                            FROM tabWarehouse w INNER JOIN (SELECT rgt FROM tabWarehouse WHERE name = %(warehouse)s) t
                            ON w.lft < t.rgt AND t.rgt < w.rgt) u ON u.name = r.warehouse
            WHERE ri.item_code = %(item)s AND r.disable = 0 and r.selling = 1 AND r.customer_group = %(customer_group)s ) AS a
        WHERE %(qty)s BETWEEN a.min_qty AND a.max_qty
        """,{"warehouse": warehouse, "item": item, "customer_group":customer_group, "qty": qty}, as_dict = 1
    )

    if data:
        return data
    else:
        return []

@frappe.whitelist()
def configuration_280924(user):    
    data = frappe.get_doc("Shop", {"user":user})
    nfc = frappe.db.sql(
        """
        SELECT CASE WHEN COUNT(c.nfc_only) > 0 THEN 0 ELSE 1 END AS nfc_only
        FROM tabShop s INNER JOIN `tabShop Territory` t ON t.parent = s.name INNER JOIN tabCustomer c ON t.territory = c.territory 
        WHERE c.nfc_only = 0 AND s.name = %s
        """,
        (data.name,),
        as_dict=1
    )
    #data.update({"nfc_only":nfc[0].nfc_only})
    return frappe._dict({
        "business_info": data,
        "nfc_only":nfc[0].nfc_only,
        "currency_symbol": data.currency_symbol,
        "base_urls": {
            "category_image_url": data.category_image_url,
            "brand_image_url": data.brand_image_url,
            "product_image_url": data.product_image_url,
            "supplier_image_url": data.supplier_image_url,
            "shop_image_url": data.shop_image_url,
            "admin_image_url": data.admin_image_url,
            "customer_image_url": data.customer_image_url,
        },
        "time_zone": get_timezones(),
    })

@frappe.whitelist()
def incomeComparision(shop):
    year_income = frappe.db.sql(
        """
        SELECT  `year`, `month`, IFNULL(net_total, 0) as net_total
        FROM(
            SELECT YEAR(posting_date) as 'year', MONTH(posting_date) as 'month', SUM(grand_total) as net_total
            FROM `tabSales Invoice`
            WHERE shop = %s AND YEAR(posting_date) = YEAR(CURDATE())
            GROUP BY YEAR(posting_date), MONTH(posting_date)
        ) AS t
        """,(shop), as_dict=1
    )
    last_year_income = frappe.db.sql(
        """
        SELECT  `year`, `month`, IFNULL(net_total, 0) as net_total
        FROM(
            SELECT YEAR(posting_date) as 'year', MONTH(posting_date) as 'month', SUM(grand_total) as net_total
            FROM `tabSales Invoice`
            WHERE shop = %s AND (YEAR(posting_date) = YEAR(CURDATE()) -  1)
            GROUP BY YEAR(posting_date), MONTH(posting_date)
        ) AS t
        """,(shop), as_dict=1
    )

    return frappe._dict({
        "year_income": year_income,
        "last_year_income": last_year_income,
    })


@frappe.whitelist()
def incomeRevenue(shop):
    income_data = frappe.db.sql(
        """
        SELECT SUM(amount) as 'total_amount', YEAR(`date`) as 'year', MONTH(`date`) as 'month'
        FROM `tabShop Transaction`
        WHERE tran_type = 'Income' AND shop = %s
        GROUP BY YEAR(`date`),MONTH(`date`)
        """,(shop), as_dict=1
    )
    expense_data = frappe.db.sql(
        """
        SELECT SUM(amount) as 'total_amount', YEAR(`date`) as 'year', MONTH(`date`) as 'month'
        FROM `tabShop Transaction`
        WHERE tran_type = 'Expense'
        GROUP BY YEAR(`date`),MONTH(`date`)
        """, as_dict=1
    )

    return frappe._dict({
        "year_wise_expense": expense_data,
        "year_wise_income": income_data,
    })


@frappe.whitelist()
def incomeSummary(shop,cond):
    condition = " "
    if cond == "today":
        condition += " AND posting_date = CURDATE()"
    elif cond == "month":
        condition += " AND MONTH(posting_date) = MONTH(CURDATE())"
    data = frappe.db.sql(
        """
        SELECT (SELECT SUM(total_qty) as total_qty
        FROM `tabSales Invoice`
        WHERE shop=%(shop)s AND YEAR(posting_date) = YEAR(CURDATE()) AND docstatus = 1 {condition}) as total_qty,
        (SELECT SUM(grand_total) as net_total
        FROM `tabSales Invoice`
        WHERE shop=%(shop)s AND YEAR(posting_date) = YEAR(CURDATE()) AND docstatus = 1 {condition}) as net_total,
        (SELECT SUM(paid_amount) as paid_amount
        FROM `tabPayment Entry`
        WHERE shop=%(shop)s AND YEAR(posting_date) = YEAR(CURDATE()) AND docstatus = 1 {condition}) as paid_amount

        """.format(condition=condition),{"shop":shop},as_dict=1
    )

    return frappe._dict({
        "incomeSummary": data[0],
    })

@frappe.whitelist()
def revenueSumary(shop,cond):
    condition = " "
    if cond == "today":
        condition += " AND date = CURDATE()"
    elif cond == "month":
        condition += " AND MONTH(date) = MONTH(CURDATE())"
    data = frappe.db.sql(
        """
        SELECT IFNULL(SUM(total_payable), 0) AS total_payable,
            IFNULL(SUM(total_receivable), 0) AS total_receivable,
            IFNULL(SUM(total_income), 0) AS total_income,
            IFNULL(SUM(total_expense), 0) AS total_expense
        FROM(
            SELECT 
                CASE WHEN tran_type = 'Payable' THEN 
                    CASE WHEN debit = 1 THEN amount ELSE -amount END 
                END AS total_payable,
                
                CASE WHEN tran_type = 'Receivable' THEN 
                    CASE WHEN debit = 1 THEN amount ELSE -amount END 
                END AS total_receivable,
                
                CASE WHEN tran_type = 'Income' THEN amount END AS total_income,
                CASE WHEN tran_type = 'Expense' THEN amount END AS total_expense
            FROM `tabShop Transaction`
            WHERE shop=%s {condition}
        ) AS t
        """.format(condition=condition),(shop),as_dict=1
    )

    return frappe._dict({
        "revenueSummary": data[0],
    })
    
@frappe.whitelist()
def get_settings():
    data = frappe.get_doc('Shop Settings')
    return frappe._dict({
        "total": 1,
        "limit": 0,
        "offset": 0,
        "mode_of_payment": data.mode_of_payment,
    })    

#@frappe.whitelist(allow_guest=True)
@frappe.whitelist()
def get_categories(shop, limit=10, offset=0):
    data = frappe.db.get_all("Shop Item Category", ["*"], filters={"shop":shop}, limit=limit,limit_start=offset)
    return frappe._dict({
        "total": len(data),
        "limit": limit,
        "offset": offset,
        "categories": data,
    })

#@frappe.whitelist(allow_guest=True)
@frappe.whitelist()
def get_invoices(name):
    data = frappe.get_doc("Sales Invoice", name)
    tax_id = frappe.db.get_value("Customer", data.customer, "tax_id")
    data.update({"tax_id":tax_id})
    return frappe._dict({
        "success": True,
        "invoice": data,
    })

#@frappe.whitelist(allow_guest=True)
@frappe.whitelist()
def get_documents(doctype=None,list_name=None,shop=None, limit=10, offset=0,name=None, company=None, nfc_only=1):
    if not doctype in ["Shop Invoice", "Shop Item"]:
        data = frappe.db.get_all(doctype, ["*"], filters={"shop":shop}, limit=limit,limit_start=offset)
        data_list =  frappe._dict({
            "total": len(data),
            "limit": limit,
            "offset": offset,
            list_name: data,
        })
    if doctype in ["Shop Item Category"]:

        data2 = data_list[list_name]
        for i in data2:
            i.update({
                "name": i["label"], 
                "id": i["name"],
                "createdAt": i["creation"], 
                "updatedAt": i["modified"],
            })
    elif doctype in ["Shop Account"]:

        data2 = data_list[list_name]
        for i in data2:
            i.update({
                "account": i["label"], 
                "id": i["name"],
                "createdAt": i["creation"], 
                "updatedAt": i["modified"],
            })

    elif doctype in ["Shop Customer"]:
        if int(nfc_only) != 99:
            data = frappe.db.sql(
                """
                SELECT (SELECT COUNT(*) + 1 FROM tabCustomer t2 WHERE t2.name <= t1.name) AS id,
                t1.name,CASE WHEN t1.name <> t1.customer_name THEN CONCAT(t1.name,' ',t1.customer_name) ELSE t1.customer_name END AS customer_name,
                t1.customer_name as description, 
                t1.mobile_no as mobile,t1.email_id as email,t1.image, 0 as balance, t1.creation as created_at, t1.modified as updated_at,
                t1.territory, t1.warehouse, t1.company, t1.branch, t1.currency, t1.sales_person, t1.default_price_list as selling_price_list, t1.tax_id,
                t1.custom_b2c, t1.tax_id, t1.custom_other_buying_id, t1.nfc_only, t1.signature
                FROM (
                    SELECT c.*, s.warehouse, s.company, s.branch, s.currency, s.sales_person 
                    FROM tabShop s INNER JOIN `tabShop Territory` t ON t.parent = s.name INNER JOIN tabCustomer c ON t.territory = c.territory 
                    WHERE s.name = %(shop)s and CONCAT(c.name,' ',lower(c.customer_name)) LIKE CONCAT('%%',lower(%(name)s),'%%') AND c.nfc_only= %(nfc_only)s
                ) AS t1
                LIMIT %(limit)s OFFSET %(offset)s
                """,{"shop":shop, "name":name, "nfc_only": nfc_only, "limit":int(limit),"offset":int(offset)}, as_dict=1
            )
        else:
            data = frappe.db.sql(
                """
                SELECT (SELECT COUNT(*) + 1 FROM tabCustomer t2 WHERE t2.name <= t1.name) AS id,
                t1.name,CASE WHEN t1.name <> t1.customer_name THEN CONCAT(t1.name,' ',t1.customer_name) ELSE t1.customer_name END AS customer_name,
                t1.customer_name as description, 
                t1.mobile_no as mobile,t1.email_id as email,t1.image, 0 as balance, t1.creation as created_at, t1.modified as updated_at,
                t1.territory, t1.warehouse, t1.company, t1.branch, t1.currency, t1.sales_person, t1.default_price_list as selling_price_list, t1.tax_id,
                t1.custom_b2c, t1.tax_id, t1.custom_other_buying_id, t1.nfc_only, t1.signature
                FROM (
                    SELECT c.*, s.warehouse, s.company, s.branch, s.currency, s.sales_person 
                    FROM tabShop s INNER JOIN `tabShop Territory` t ON t.parent = s.name INNER JOIN tabCustomer c ON t.territory = c.territory 
                    WHERE s.name = %(shop)s and CONCAT(c.name,' ',lower(c.customer_name)) LIKE CONCAT('%%',lower(%(name)s),'%%')
                ) AS t1
                LIMIT %(limit)s OFFSET %(offset)s
                """,{"shop":shop, "name":name, "limit":int(limit),"offset":int(offset)}, as_dict=1
            )

        shop_doc = frappe.get_doc("Shop", shop)
        pending_amount = get_pending_amount(shop_doc)

        for i in data:
            outstanding_amt = get_customer_outstanding(
                i.name, company, ignore_outstanding_sales_order=True
            )
            credit_limit = get_credit_limit(i.name, company)

            bal = flt(credit_limit) - flt(outstanding_amt)

            sql_data = frappe.db.sql(
                """
                SELECT SUM(t.net_total) AS net_total, SUM(t.paid_amount) AS paid_amount, SUM(total_qty) AS total_qty, SUM(invoices_count) AS invoices_count
                FROM(
                    SELECT SUM(grand_total) as net_total, 0 as paid_amount, SUM(total_qty) AS total_qty, COUNT(name) as invoices_count
                    FROM `tabSales Invoice`
                    WHERE customer=%(customer)s AND docstatus = 1 AND YEAR(posting_date) = YEAR(CURDATE())
                    UNION
                    SELECT  0 as net_total, SUM(paid_amount) as paid_amount, 0 AS total_qty, 0 as invoices_count
                    FROM `tabPayment Entry`
                    WHERE party=%(customer)s AND docstatus =1 AND YEAR(posting_date) = YEAR(CURDATE())
                ) AS t
                """,{"customer": i.name}, as_dict=1
            )

            i.update({
                "balance": bal,
                "outstanding": outstanding_amt,
                "credit_limit": credit_limit,
                "total_invoice": sql_data[0].net_total,
                "cash_collected": sql_data[0].paid_amount,
                "total_qty": sql_data[0].total_qty,
                "invoices_count": sql_data[0].invoices_count,
                "shop_pending": pending_amount,
            })
        #if name:
            # Filter data where the name starts with name
        #    data = [entry for entry in data if name in entry['customer_name'].lower()]

        data_list =  frappe._dict({
            "total": len(data),
            "limit": limit,
            "offset": offset,
            list_name: data,
        })

    elif doctype in ["Shop Product"]:
        data = frappe.db.sql(
            """
            SELECT p.name as id,p.product_code,p.title,p.unit_type,p.unit_value,p.brand,p.category_ids,p.purchase_price, p.selling_price,p.discount_type,p.discount,
                p.tax, SUM(b.actual_qty) as quantity,p.image,p.order_count,p.supplier_id,p.company_id, p.creation as createdAt, p.modified as updatedAt
            FROM `tabShop` s CROSS JOIN `tabShop Product` p INNER JOIN tabBin b ON p.product_code = b.item_code AND s.warehouse = b.warehouse
            INNER JOIN tabItem i ON i.name = p.product_code
            WHERE i.disabled = 0 and b.actual_qty > 0 AND s.name = %(shop)s
            GROUP BY p.name,p.product_code,p.title,p.unit_type,p.unit_value,p.brand,p.category_ids,p.purchase_price, p.selling_price,p.discount_type,p.discount,
                p.tax,p.image,p.order_count,p.supplier_id,p.company_id, p.creation, p.modified
            LIMIT %(limit)s OFFSET %(offset)s
            """,{"shop":shop, "limit":int(limit),"offset":int(offset)}, as_dict=1
        )

        if name:
            # Filter data where the name starts with name
            data = [entry for entry in data if name in entry['title'].lower()]

        data_list =  frappe._dict({
            "total": len(data),
            "limit": limit,
            "offset": offset,
            list_name: data,
        })

    elif doctype in ["Shop Invoice"]:
        data = frappe.db.sql(
            """
            SELECT i.name as invoice_number, i.posting_date as date, i.grand_total as net_total, i.paid_amount, i.outstanding_amount, i.customer
            FROM `tabSales Invoice` i INNER JOIN `tabShop` s ON i.sales_reconciliation = s.sales_person
            WHERE i.outstanding_amount > 0 AND s.name= %(shop)s AND i.customer = %(name)s AND i.docstatus = 1 and i.status <> 'Credit Note Issued'
            """,{"shop":shop,"name":name}, as_dict=1
        )

        data_list =  frappe._dict({
            "total": len(data),
            "limit": limit,
            "offset": offset,
            list_name: data,
        })

    elif doctype in ["Shop Item"]:
        data = frappe.db.sql(
            """
            SELECT *
            FROM `tabShop Item`
            WHERE status = 0 AND parent = %(shop)s
            """,{"shop":shop}, as_dict=1
        )

        data_list =  frappe._dict({
            "total": len(data),
            "limit": limit,
            "offset": offset,
            list_name: data,
        })

    return data_list


@frappe.whitelist()
def get_daily_report(limit=10, offset=0):
    request_data = frappe.request.data
    request_data_str = request_data.decode('utf-8')
    request_dict = frappe.parse_json(request_data_str)

    shop = request_dict.get('shop', None)
    start = request_dict.get('start', None)
    end = request_dict.get('end', None)
    code = request_dict.get('code', None)

    condition = ""
    parameters = {"shop": shop}

    if start:
        condition += " AND posting_date >= %(start)s"
        parameters["start"] = start
    if end:
        condition += " AND posting_date <= %(end)s"
        parameters["end"] = end

    si_condition = ""
    if code:
        si_condition += " AND customer = %(customer)s"
        parameters["customer"] = code

    pe_condition = ""
    if code:
        pe_condition += " AND party = %(party)s"
        parameters["party"] = code

    data = frappe.db.sql(
        """
        SELECT t.posting_date, SUM(t.net_total) AS net_total, SUM(t.paid_amount) AS paid_amount, total_qty
        FROM(
            SELECT posting_date, SUM(grand_total) as net_total, 0 as paid_amount, SUM(total_qty) AS total_qty
            FROM `tabSales Invoice`
            WHERE shop=%(shop)s AND docstatus <> 2 {condition} {si_condition}
            GROUP BY posting_date
            UNION
            SELECT DISTINCT posting_date, 0 as net_total, SUM(paid_amount) as paid_amount, 0 AS total_qty
            FROM `tabPayment Entry`
            WHERE shop=%(shop)s AND docstatus <> 2 {condition} {pe_condition}
            GROUP BY posting_date
        ) AS t
        GROUP BY t.posting_date
        """.format(condition=condition, si_condition=si_condition, pe_condition=pe_condition),parameters, as_dict=1
    )
    return frappe._dict({
        "total": len(data),
        "limit": limit,
        "offset": offset,
        "categories": data,
    })


@frappe.whitelist()
def create_order():
    # Get the request data
    request_data = frappe.request.data
    request_data_str = request_data.decode('utf-8')
    request_dict = frappe.parse_json(request_data_str)
    cart_data = request_dict.get('cart')
    customer = request_dict.get('customer_name')

    selling_price_list = frappe.db.get_value("Customer",customer,"default_price_list")

    order_details = []
    for i in cart_data:
        details = frappe._dict({
            "doctype": "Sales Order Item",
            "item_code": i["product_code"],
            "qty": i["quantity"],            
        })
        order_details.append(details)

    args = frappe._dict(
        {
            "doctype": "Sales Order",
            "customer": request_dict.get('customer_name'),
            "transaction_date": frappe.utils.getdate(),
            "delivery_date": frappe.utils.getdate(),
            "selling_price_list": selling_price_list,
            "items": order_details,
        }
    )
    try:
        sale = frappe.get_doc(args)
        #sale.ignore_pricing_rule = 1
        sale.insert()
        sale.submit()
    except frappe.DoesNotExistError:
            return None
        
    return str("OK")


def get_item_batches(warehouse, item_code, promo_data, branch, max_qty, is_free_item = False):
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

    return dispatch_by_batch(batches,promo_data, branch, item_code, max_qty, is_free_item)




def dispatch_by_batch(batches,promo_data, branch, item_code, max_qty, is_free_item = False):
    """
    Process and dispatch items based on batches and promotional data.

    Parameters:
    - batches (list): List of item batches.
    - promo_data (list): List of promotional data.
    - branch (str): The branch code.
    - item_code (str): The item code.
    - max_qty (float): The maximum quantity to be dispatched.
    - is_free_item (bool): Whether the item is a free item with a rate of 0.

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


def get_item_data(item_list, item_code, qty):
    for item in item_list:
        if qty == 0:
            break

        if item["item_code"] == item_code and item["qty"] > 0 and qty > 0:
            reduced_qty = min(qty, item["qty"])

            # Update quantity in item_list
            item["qty"] -= reduced_qty
            qty -= reduced_qty

            # If quantity becomes zero, remove the item from item_list
            if item["qty"] == 0:
                item_list.remove(item)

            if qty == 0:
                return {
                    "item_list": item_list, 
                    "item_name" : item["item_name"], 
                    "description": item["description"], 
                    "uom" : item["uom"], 
                    "rate": item["rate"],
                    "income_account": item["income_account"],
                }

@frappe.whitelist()
def process_cart_data(doc):
    """
    Process cart data to generate invoice details and temp batches.

    Args:
    - invoice_name (str): Invoice name.
    - warehouse (str): Warehouse code.
    - branch (str): Branch code.
    - customer (str): Customer name.

    Returns:
    - tuple: Tuple containing invoice details (list) and temp batches (list).
    """

    invoice_details = []
    temp_batches = []

    item_list = frappe.db.sql(
        """
        SELECT item_code, item_name, description, uom, rate,income_account, SUM(qty) AS qty
        FROM `tabSales Invoice Item`
        WHERE parent = %s
        GROUP BY item_code, item_name, description, uom, rate,income_account
        ORDER BY item_code, rate
        """, (doc.name), as_dict=1
    )

    items = frappe.db.sql(
        """
        SELECT item_code, SUM(qty) AS qty
        FROM `tabSales Invoice Item`
        WHERE parent = %s
        GROUP BY item_code
        """, (doc.name), as_dict=1
    )

    for item in items:
        if item.qty == 0:
            continue
        
        max_qty = int(item.qty)

        customer_group = frappe.db.get_value("Customer", doc.get('customer'), "customer_group")
        promo_data = get_promotion(doc.get('set_warehouse'), item.get('item_code'), customer_group, max_qty)

        details, temp_batches = get_item_batches(doc.get('set_warehouse'), item.get('item_code'), promo_data, doc.branch, max_qty)        
        invoice_details.extend(details)

        if promo_data:
            for promo in promo_data:
                if promo["price_or_product_discount"] == "Product" and promo["total_free_qty"] > 0:
                    details, temp_batches = dispatch_by_batch(temp_batches, [], doc.branch, promo["free_item"], promo["total_free_qty"], True)
                    invoice_details.extend(details)

    # Clear existing items
    doc.items.clear()

    #frappe.msgprint(str(invoice_details))
    #frappe.msgprint(str(item_list))
    #frappe.msgprint("______________________________")
    # Insert new items
    for detail in invoice_details:
        #new_item = frappe.new_doc(detail)
        o = get_item_data(item_list, detail.get("item_code"), detail.get("qty"))
        #frappe.msgprint(str(detail))
        #frappe.msgprint(str(o))
        #frappe.msgprint("______________________________")
        
        if o:
            item_list = o.get("item_list")
            new_item = frappe.new_doc("Sales Invoice Item")
            new_item.update({
                "item_code": detail.get("item_code"),
                "qty": detail.get("qty"),
                "batch_no": detail.get("batch_no"),
                "rate": o.get("rate"),
                "amount": flt(detail.get("qty")) * flt(o.get("rate")),
                "item_name": o.get("item_name"),
                "description": o.get("description"),
                "uom": o.get("uom"),
                "income_account": o.get("income_account"),
                "branch": doc.branch
            })
            doc.append("items", new_item)

    #doc.save()

    return invoice_details

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

@frappe.whitelist()
def create_invoice():
    """
    Create a Sales Invoice based on the provided request data.

    Returns:
    - str: Sales Invoice name.
    """

    name=None
    sale = {}
    # Get the request data
    request_data = frappe.request.data
    request_data_str = request_data.decode('utf-8')
    request_dict = frappe.parse_json(request_data_str)
    cart_data = request_dict.get('cart')
    shop = ""
    customer = ""
    selling_price_list =""
    warehouse = ""
    company = ""
    branch = ""
    currency = ""
    sales_person = ""
    payment_type = ""
    total_amount = 0.0
    visit_name = None
    
    if request_dict.get('invoice_name'):
        name = request_dict.get('invoice_name').strip()
    if request_dict.get('customer_name'):
        customer = request_dict.get('customer_name').strip()
    if request_dict.get('selling_price_list'):
        selling_price_list = request_dict.get("selling_price_list").strip()
    if request_dict.get('warehouse'):
        warehouse = request_dict.get("warehouse").strip()
    if request_dict.get('customer_company'):
        company = request_dict.get("customer_company").strip()
    if request_dict.get('customer_branch'):
        branch = request_dict.get("customer_branch").strip()
    if request_dict.get('customer_currency'):
        currency = request_dict.get("customer_currency").strip()
    if request_dict.get('customer_sales_person'):
        sales_person = request_dict.get("customer_sales_person").strip()
    if request_dict.get('shop'):
        shop = request_dict.get("shop").strip()
    if request_dict.get('payment_type'):
        payment_type = request_dict.get('payment_type')
    if request_dict.get('total_amount'):
        total_amount = request_dict.get('total_amount')
    if request_dict.get('visit'):
        visit_name = request_dict.get('visit')

    shop_doc = frappe.get_doc("Shop", shop)
    pending_amount = get_pending_amount(shop_doc)
        
    if payment_type == "Credit":
        meta = get_meta("Customer")
        if meta.get_field("custom_customer_account_type"):
            custom_customer_account_type = frappe.db.get_value("Customer", customer,"custom_customer_account_type")
            if custom_customer_account_type != "CONTRACT CUSTOMER":
                if not shop_doc.unlimited_credit : 
                    
                    total_pending = flt(pending_amount) + flt(total_amount)
                    if flt(shop_doc.credit_limit) < total_pending :
                        frappe.throw("Your pending is {0} is more than your credit limit {1}. You can not credit to this customer!").format(str(total_pending), str(shop_doc.credit_limit))
        else:
            if not shop_doc.unlimited_credit : 
                total_pending = flt(pending_amount) + flt(total_amount)
                if flt(shop_doc.credit_limit) < total_pending :
                    frappe.throw("Your pending is {0} is more than your credit limit {1}. You can not credit to this customer!").format(str(total_pending), str(shop_doc.credit_limit))
        
        outstanding_amt = get_customer_outstanding(
            customer, company, ignore_outstanding_sales_order=True
        )
        credit_limit = get_credit_limit(customer, company)
        total_out = flt(outstanding_amt) + flt(total_amount)
        bal = flt(credit_limit) - total_out
        if bal < 0 :
            frappe.throw("The credit limit is {0}. The outstanding amount is {1}. You can no more add invoices!").format(str(credit_limit), str(total_out))

    invoice_details = []
    temp_batches = []
    for i in cart_data:
        if i["quantity"] == 0:
            continue
        
        max_qty = i["quantity"]

        customer_group = frappe.db.get_value("Customer",customer, "customer_group")
        promo_data = get_promotion(warehouse, i["product_code"], customer_group, max_qty)

        details, temp_batches = get_item_batches(warehouse, i["product_code"], promo_data, branch, max_qty)        
        invoice_details.extend(details)
        #for d in details:
        #    invoice_details.append(d)

        if len(promo_data) > 0:
            for p in promo_data:
                if p["price_or_product_discount"] == "Product" and p["total_free_qty"] > 0:
                    if i["product_code"] == p["free_item"]:
                        details, temp_batches2  = dispatch_by_batch(temp_batches,[], branch, p["free_item"], p["total_free_qty"], True)
                        invoice_details.extend(details)
                    else:
                        details, temp_batches = get_item_batches(warehouse, p["free_item"], [], branch, p["total_free_qty"], True) 
                        invoice_details.extend(details)
                elif p["price_or_product_discount"] == "Price":
                    details, temp_batches2  = dispatch_by_batch(temp_batches,[], branch, p["free_item"], p["total_free_qty"], True)
                    invoice_details.extend(details) 

    args = frappe._dict(
        {
            "doctype": "Sales Invoice",
            "customer": customer,
            "company": company,
            "branch": branch,
            "set_warehouse": warehouse,
            "update_stock": 1,
            "sales_reconciliation": sales_person,
            "selling_price_list": selling_price_list,
            "shop":shop,
            "items": invoice_details,
        }
    )

    sales_team = frappe._dict({
        "sales_person": sales_person,
        "allocated_percentage": 100,
        "doctype": "Sales Team",
    })
    if sales_team:
        args.update({"sales_team": [sales_team],})

    if payment_type:
            args.update({"payment_type": payment_type,})

    try:
        if invoice_details:
            tax = frappe._dict({
                "charge_type": "On Net Total",
                "account_head": "VAT 15% - AHW",
                "description": "VAT 15% @ 15.0",
                "rate": 15.0,
                "doctype": "Sales Taxes and Charges",
            })
            args.update({"taxes": [tax]})
            
            sale = frappe.get_doc(args)
            sale.ignore_pricing_rule = 1
            if not name:
                sale.insert()
            else :
                args.update({"name": name})
                sale.save()

            if visit_name:
                visit = frappe.get_doc("Shop Visit", visit_name)
                visit.append('details',{
                        "document_type": "Sales Invoice",
                        "document_name": sale.name,
                        "posting_date": sale.creation,
                        "amount": sale.grand_total,
                    }
                )
                visit.save()

            #Gestion du paiment
            signature = frappe.db.get_value("Customer", customer,"signature")
            if signature == 0:
                if payment_type == "Cash":
                    pay_name = create_pos_cash_payment_invoice(shop, company, customer, sale.name, branch, sale.grand_total, visit_name)
                    add_payment_to_invoice(pay_name, sale)
                    sale.save()
                    
                sale.submit()
                shop_doc.peding_amount = pending_amount + flt(total_amount)
                shop_doc.save()
                
    except UnableToSelectBatchError as e:
        frappe.log_error(f"Unable to select batch for {args}", "Batch Selection Error")
        frappe.throw(_("Unable to select batch for Args: {0}".format( args)))
    
    except frappe.DoesNotExistError:
        return None
        
    return str(sale.name)


@frappe.whitelist()
def get_name_list(doctype,filters=None, limit=10, offset=0):
    data = []

    if doctype in ["Sales Order", "Sales Invoice", "Payment Entry"]:
        if filters == None:
            filter_list = []
        else:
            filter_list = json.loads(filters)
        filter_list.append(["docstatus", "=", 1])
        filters = json.dumps(filter_list)

    if filters:
        data = frappe.db.get_list(doctype, filters=filters, limit=limit,limit_start=offset)
    else:
        data = frappe.db.get_list(doctype)

    names = []
    for d in data:
        names.append(d.name)

    return names


@frappe.whitelist()
def create_payment_entry():
    payment = {}
    # Get the request data
    request_data = frappe.request.data
    request_data_str = request_data.decode('utf-8')
    request_dict = frappe.parse_json(request_data_str)
    mode_of_payment = request_dict.get("mode_of_payment").strip()
    company = request_dict.get("company").strip()
    shop = request_dict.get("shop").strip()
    reference_no = request_dict.get("reference_no").strip()
    received_amount = request_dict.get('paid_amount')
    visit_name = None
    if request_dict.get('visit'):
        visit_name = request_dict.get('visit')

    shop_doc = frappe.get_doc("Shop", shop)

    data = frappe.db.sql(
        """
        SELECT m.default_account,a.account_currency
        FROM `tabMode of Payment Account` m INNER JOIN tabAccount a ON a.name = m.default_account
        WHERE m.parent = %s AND m.company = %s
        """,(mode_of_payment,company), as_dict = 1
    )
    
    account = data[0].default_account
    account_currency = data[0].account_currency
    #exchange_rate = get_exchange_rate("USD","CDF") //todo

    
    request_dict.update({
        "doctype": "Payment Entry",
        "received_amount": received_amount,
        "target_exchange_rate": 1.0,
        "paid_to": account,
        "paid_to_account_currency": account_currency,
        "shop": shop,
        "reference_no": reference_no,
        "reference_date": frappe.utils.getdate(),
    })

    try:
        payment = frappe.get_doc(request_dict)
        payment.submit()

        shop_doc = frappe.get_doc("Shop", shop)
        total_pending = get_pending_amount(shop_doc)
        shop_doc.peding_amount = total_pending
        shop_doc.save()

        if visit_name:
            visit = frappe.get_doc("Shop Visit", visit_name)
            visit.append('details',{
                    "document_type": "Payment Entry",
                    "document_name": payment.name,
                    "posting_date": payment.creation,
                    "amount": received_amount,
                }
            )
            visit.save()

    except frappe.DoesNotExistError:
        return None
    except Exception as e:
    # Handle other exceptions by logging or custom logic
        frappe.throw(f"An error occurred: {str(e)}")
        
    return str(payment.name)


def create_pos_cash_payment_invoice(shop, company, customer, invoice, branch, grand_total, visit_name = None):
    cash_mode_list = frappe.db.sql(
        """
        SELECT mode_of_payment
        FROM `tabShop Mode Payment`
        WHERE parent = %s AND mode_of_payment LIKE  '%%Cash%%'
        """, (shop), as_dict = 1
    )

    cash_mode = ""
    if cash_mode_list:
        cash_mode = cash_mode_list[0].mode_of_payment
    else:
        # Handle the case when no cash mode is found
        frappe.throw("No cash mode found for the shop.")

    data = frappe.db.sql(
        """
        SELECT m.default_account,a.account_currency
        FROM `tabMode of Payment Account` m INNER JOIN tabAccount a ON a.name = m.default_account
        WHERE m.parent = %s AND m.company = %s
        """,(cash_mode,company), as_dict = 1
    )

    account = data[0].default_account
    account_currency = data[0].account_currency

    args = {
        "doctype": "Payment Entry",
        "party_type": "Customer",
        "party": customer,
        "paid_amount": grand_total,
        "received_amount": grand_total,
        "target_exchange_rate": 1.0,
        "paid_to": account,
        "paid_to_account_currency": account_currency,
        "shop": shop,
        "reference_no": "Cash Sales",
        "reference_date": frappe.utils.getdate(),
        #"references":[{"reference_doctype": "Sales Invoice", "reference_name": invoice, "allocated_amount": grand_total}],
        "branch": branch
    }

    signature = frappe.db.get_value("Customer", customer,"signature")
    pay_doc = frappe.get_doc(args)
    pay_doc.insert()
    pay_doc.submit()
        

    if visit_name:
        visit = frappe.get_doc("Shop Visit", visit_name)
        visit.append('details',{
                "document_type": "Payment Entry",
                "document_name": pay_doc.name,
                "posting_date": pay_doc.creation,
                "amount": grand_total,
            }
        )
        visit.save()

    return pay_doc.name

#to delete
def create_pos_cash_invoice_payment(shop, company, customer, invoice, branch, grand_total, visit_name = None):
    #pos_doc = frappe.get_doc("Shop", shop)
    #cash_mode_list = frappe.db.get_list("Shop Mode Payment", filters={"parent": shop, "mode_of_payment": ["LIKE","%Cash%"]}, fields=["mode_of_payment"])
    shop_doc = frappe.get_doc("Shop", shop)
    cash_mode_list = frappe.db.sql(
        """
        SELECT mode_of_payment
        FROM `tabShop Mode Payment`
        WHERE parent = %s AND mode_of_payment LIKE  '%%Cash%%'
        """, (shop), as_dict = 1
    )

    cash_mode = ""
    if cash_mode_list:
        cash_mode = cash_mode_list[0].mode_of_payment
    else:
        # Handle the case when no cash mode is found
        frappe.throw("No cash mode found for the shop.")

    data = frappe.db.sql(
        """
        SELECT m.default_account,a.account_currency
        FROM `tabMode of Payment Account` m INNER JOIN tabAccount a ON a.name = m.default_account
        WHERE m.parent = %s AND m.company = %s
        """,(cash_mode,company), as_dict = 1
    )

    account = data[0].default_account
    account_currency = data[0].account_currency

    args = {
        "doctype": "Payment Entry",
        "party_type": "Customer",
        "party": customer,
        "paid_amount": grand_total,
        "received_amount": grand_total,
        "target_exchange_rate": 1.0,
        "paid_to": account,
        "paid_to_account_currency": account_currency,
        "shop": shop,
        "reference_no": "Cash Sales",
        "reference_date": frappe.utils.getdate(),
        "references":[{"reference_doctype": "Sales Invoice", "reference_name": invoice, "allocated_amount": grand_total}],
        "branch": branch
    }

    signature = frappe.db.get_value("Customer", customer,"signature")
    pay_doc = frappe.get_doc(args)
    pay_doc.insert()
    if signature == 0:
        pay_doc.submit()

    if visit_name:
        visit = frappe.get_doc("Shop Visit", visit_name)
        visit.append('details',{
                "document_type": "Payment Entry",
                "document_name": pay_doc.name,
                "posting_date": pay_doc.creation,
                "amount": grand_total,
            }
        )
        visit.save()

        total_pending = get_pending_amount(shop_doc)
        shop_doc.peding_amount = total_pending
        shop_doc.save()
    

def get_dates_between(start_date, end_date):
    """
    Get all dates between start_date and end_date (inclusive).
    
    Args:
    - start_date (str): Start date in the format 'YYYY-MM-DD'.
    - end_date (str): End date in the format 'YYYY-MM-DD'.
    
    Returns:
    - list: List of date objects between start_date and end_date.
    """
    start_date_obj = frappe.utils.getdate(start_date)
    end_date_obj = frappe.utils.getdate(end_date)

    # Calculate the number of days between start_date and end_date
    delta = end_date_obj - start_date_obj

    # Generate a list of dates between start_date and end_date
    dates_list = [start_date_obj + timedelta(days=i) for i in range(delta.days + 1)]

    return dates_list


@frappe.whitelist()
def get_sku_wise_daily_report(limit=10, offset=0):
    request_data = frappe.request.data
    request_data_str = request_data.decode('utf-8')
    request_dict = frappe.parse_json(request_data_str)

    shop = request_dict.get('shop', None)
    start = request_dict.get('start', None)
    end = request_dict.get('end', None) 

    dates_list = get_dates_between(start, end)
    
    shop_doc = frappe.get_doc("Shop", shop)
    company_doc = frappe.get_doc("Company", shop_doc.company)
    company_address = frappe.get_doc("Address", company_doc.name)
    
    sales_person = shop_doc.sales_person

    data = []

    #end_limit = limit + offset if limit + offset < len(dates_list) else len(dates_list) 
    #start_limit = offset  if offset < end_limit else end_limit
    for d in dates_list: # [start_limit: end_limit]:
        sum_doc = frappe.db.sql(
            """
            SELECT t.posting_date, SUM(t.net_total) AS net_total, SUM(t.paid_amount) AS paid_amount, SUM(total_qty) AS total_qty, 
                SUM(grand_total) AS grand_total, SUM(total_tax) AS total_tax, SUM(total_cash) AS total_cash, SUM(total_credit) AS total_credit,
                SUM(cash_count) AS cash_count, SUM(credit_count) AS credit_count
            FROM(
                SELECT posting_date, SUM(net_total) as net_total, 0 as paid_amount, SUM(total_qty) AS total_qty, 
                    SUM(grand_total) AS grand_total, SUM(total_taxes_and_charges) AS total_tax,
                    SUM(CASE WHEN payment_type = 'Cash' THEN grand_total ELSE 0 END) AS total_cash,
                    SUM(CASE WHEN payment_type <> 'Cash' THEN grand_total ELSE 0 END) AS total_credit,
                    SUM(CASE WHEN payment_type = 'Cash' THEN 1 ELSE 0 END) AS cash_count,
                    SUM(CASE WHEN payment_type <> 'Cash' THEN 1 ELSE 0 END) AS credit_count
                FROM `tabSales Invoice`
                WHERE shop=%(shop)s AND docstatus = 1 AND posting_date = %(date)s
                GROUP BY posting_date
                UNION
                SELECT DISTINCT posting_date, 0 as net_total, SUM(paid_amount) as paid_amount, 0 AS total_qty, 
                    0 AS grand_total, 0 AS total_tax, 0 AS total_cash, 0 AS total_credit, 0 AS cash_count, 0 AS credit_count
                FROM `tabPayment Entry`
                WHERE shop=%(shop)s AND docstatus = 1  AND posting_date = %(date)s
                GROUP BY posting_date
            ) AS t
            GROUP BY t.posting_date
            """, {"shop": shop, "date": d}, as_dict=1
        )

        tax_text = "$.VAT 15% - AHW"
        
        details_doc = frappe.db.sql(
            """
            SELECT d.item_code, SUM(d.qty) AS qty, MAX(d.rate) AS rate, SUM(d.amount) AS amount, 
                SUM(SUBSTRING_INDEX(IFNULL(SUBSTRING(item_tax_rate, 2, LENGTH(item_tax_rate) - 2),0),':',-1) / 100 * d.amount) AS tax_amount,
                SUM((100 + SUBSTRING_INDEX(IFNULL(SUBSTRING(item_tax_rate, 2, LENGTH(item_tax_rate) - 2),0),':',-1)) / 100 * d.amount) AS total
            FROM `tabSales Invoice Item` d 
            INNER JOIN `tabSales Invoice` i ON d.parent = i.name
            WHERE i.shop = %(shop)s AND i.posting_date = %(date)s AND i.docstatus = 1
            GROUP BY d.item_code
            """, {"shop": shop, "date": d, "tax": tax_text}, as_dict=1
        )
        
        details = []
        if sum_doc:
            if details_doc:
                details.extend(details_doc)
            args = {
                "shop": shop,
                "company": shop_doc.company,
                "salesman": shop_doc.sales_person,
                "warehouse": shop_doc.warehouse,
                "address": company_address.pincode + ", " + company_address.address_line1,
                "vat_no": shop_doc.vat_reg_no,
                "branch": shop_doc.branch,
                "total_qty": sum_doc[0].total_qty,
                "date": d,
                "total_tax": sum_doc[0].total_tax if sum_doc and sum_doc[0].total_tax else 0.0,
                "grand_total": sum_doc[0].grand_total if sum_doc and sum_doc[0].grand_total else 0.0,
                "total_cash": sum_doc[0].total_cash if sum_doc and sum_doc[0].total_cash else 0.0,
                "total_credit": sum_doc[0].total_credit if sum_doc and sum_doc[0].total_credit else 0.0,
                "paid_amount": sum_doc[0].paid_amount if sum_doc and sum_doc[0].paid_amount else 0.0,
                "cash_value": ((sum_doc[0].grand_total - sum_doc[0].paid_amount) if sum_doc[0].grand_total - sum_doc[0].paid_amount > 0 else 0.0) if sum_doc and sum_doc[0].grand_total and sum_doc[0].paid_amount else 0.0,
                "cash_count": sum_doc[0].cash_count if sum_doc and sum_doc[0].cash_count else 0.0,
                "credit_count": sum_doc[0].credit_count if sum_doc and sum_doc[0].credit_count else 0.0,
                "details": details,
            }
            
            data.append(args)

    return frappe._dict({
        "total": len(data),
        "limit": limit,
        "offset": offset,
        "sku_daily_report": data,
    })

@frappe.whitelist()
def get_visits(shop, start, end, limit=10, offset=0):

    data = frappe.db.sql(
        """
        SELECT *
        FROM `tabShop Visit`
        WHERE shop= %(shop)s AND end BETWEEN %(start)s AND %(end)s
        LIMIT %(limit)s OFFSET %(offset)s
        """, {"shop": shop, "start": start, "end": end, "limit": limit, "offset":offset}, as_dict=1
    )

    for d in data:        
        transactions = []
        transactions_doc = frappe.db.sql(
            """
            SELECT name,creation as `date`, SUM(grand_total) as value, 'Invoice' AS `type`
            FROM `tabSales Invoice`
            WHERE shop=%(shop)s AND docstatus = 1 AND CONVERT(creation, date) = CONVERT( %(date)s, date)
            GROUP BY name,creation
            UNION
            SELECT name,creation, SUM(paid_amount) as value, 'Payment' AS `type`
            FROM `tabPayment Entry`
            WHERE shop=%(shop)s AND docstatus = 1 AND CONVERT(creation, date) = CONVERT( %(date)s, date)
            GROUP BY name,creation
            """, { "shop": shop, "date": d.end }, as_dict=1
        )
        
        details = []
        if transactions_doc:
            transactions.extend(transactions_doc)
            d.update({"transactions": transactions})

    return frappe._dict({
        "total": len(data),
        "limit": limit,
        "offset": offset,
        "visits": data,
    })

def add_payment_to_invoice(name, sale):
    unallocated_payment_entries = frappe.db.sql(
        """
            select 'Payment Entry' as reference_type, name as reference_name, posting_date,
            remarks, unallocated_amount as amount
            from `tabPayment Entry`
            where name = %s and docstatus = 1 
        """, (name),
        as_dict=1,
    )

    pay = unallocated_payment_entries[0]

    advance_row = {
        "doctype":  "Sales Invoice Advance",
        "reference_type": pay.reference_type,
        "reference_name": pay.reference_name,
        "remarks": "Cash Payment",
        "advance_amount": flt(pay.amount),
        "allocated_amount": flt(pay.amount),
        "ref_exchange_rate": 1,  
    }

    sale.append("advances", advance_row)



#///////////////////SUPERMARKET//////////////////////////////////////////
@frappe.whitelist()
def update_item():
    request_data = frappe.request.data
    request_data_str = request_data.decode('utf-8')
    request_dict = frappe.parse_json(request_data_str)

    name = request_dict.get('name', None)

    frappe.db.set_value('Shop Item', name, 
    {
        "status": 1,
        "sync": 1,
    })
    frappe.db.commit()




