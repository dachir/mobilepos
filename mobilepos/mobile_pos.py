import frappe
import re
from frappe import _
from frappe.utils import flt, getdate, get_time, now_datetime, add_to_date
from datetime import datetime,timedelta
from frappe.core.doctype.user.user import get_timezones, generate_keys
from frappe.utils.password import check_password, update_password
from erpnext.setup.utils import get_exchange_rate
from erpnext.selling.doctype.customer.customer import get_credit_limit, get_customer_outstanding
from frappe.model.meta import get_meta
from erpnext.stock.doctype.batch.batch import UnableToSelectBatchError
from shapely.geometry import Point, Polygon
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry as map_pe
from frappe.utils.background_jobs import enqueue
#from frappe.website.doctype.personal_data_deletion_request.personal_data_deletion_request import 



import json

def get_balance(customer, company):
    outstanding_amt = get_customer_outstanding(
        customer, company, ignore_outstanding_sales_order=i.bypass_credit_limit_check
    )
    credit_limit = get_credit_limit(customer, company)

    return flt(credit_limit) - flt(outstanding_amt)

#def get_promotion(warehouse, item, customer_group, qty):
@frappe.whitelist()
def get_promotion(warehouse, item, customer, qty):
    #customer_group = frappe.db.get_value("Customer",customer, "customer_group")
    data = []

    #data = frappe.db.sql(
    #    """
    #    SELECT *, (%(qty)s DIV a.min_qty) * a.free_qty AS total_free_qty
    #    FROM(
    #        SELECT DISTINCT ri.item_code, r.name,r.price_or_product_discount,
    #            CASE WHEN r.same_item THEN ri.item_code ELSE r.free_item END as free_item,
    #            min_qty,
    #            CASE WHEN r.price_or_product_discount = 'Product' THEN free_qty ELSE 0 END  as free_qty, 
    #            CASE WHEN r.price_or_product_discount = 'Price' THEN  rate ELSE 0 END as rate,
    #            CASE WHEN max_qty = 0 THEN 999999999999 ELSE max_qty END as max_qty
    #        FROM `tabPricing Rule` r INNER JOIN `tabPricing Rule Item Code` ri ON ri.parent = r.name
    #        WHERE ri.item_code = %(item)s AND r.disable = 0 and r.selling = 1 AND CURDATE() BETWEEN r.valid_from AND IFNULL(r.valid_upto, '3099-12-31')
    #        AND (r.customer_group = %(customer_group)s OR r.customer = %(customer)s) 
    #        AND (
    #            length(r.warehouse) = 0
    #            OR EXISTS (
    #                SELECT 1
    #                FROM tabWarehouse w
    #                INNER JOIN (
    #                    SELECT lft, rgt 
    #                    FROM tabWarehouse 
    #                    WHERE name = %(warehouse)s
    #                ) t ON w.lft >= t.lft AND w.rgt <= t.rgt
    #                WHERE w.name = r.warehouse
    #            )
    #        )
    #        
    #        ) AS a
    #    WHERE %(qty)s BETWEEN a.min_qty AND a.max_qty
    #    """,{"warehouse": warehouse, "item": item, "customer":customer, "customer_group":customer_group, "qty": qty}, as_dict = 1
    #)

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


@frappe.whitelist()
def get_last_invoice_within_5_minutes():
    # Read POST data
    data = frappe.local.form_dict
    shop = data.get("shop")
    customer = data.get("customer")

    # 1. Compute the threshold datetime (now − 4 minutes)
    threshold = add_to_date(now_datetime(), minutes=-5)

    # 2. Query for invoices created on or after that threshold
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=[
            ["creation", ">=", threshold],
            ["shop", "=", shop],
            ["customer", "=", customer],               # only this shop
            ["docstatus", "=", 1],          # only submitted invoices 
            ["custom_print", "<", 1],
        ],
        fields=["name"],
        order_by="creation desc",
        limit_page_length=1
    )

    # 3. If none found, return a helpful message
    if not invoices:
        return {"success": False, "message": "No Sales Invoice was created in the last 4 minutes."}

    # 4. Otherwise, take the first (newest), look up tax_id, and return
    invoice_name = invoices[0]
    data = frappe.get_doc("Sales Invoice", invoice_name)
    tax_id = frappe.db.get_value("Customer", data.customer, "tax_id")
    data.update({"tax_id":tax_id})

    return {"success": True, "invoice": data}


#@frappe.whitelist(allow_guest=True)
@frappe.whitelist()
def get_documents(doctype=None,list_name=None,shop=None, limit=10, offset=0,name=None, company=None, nfc_only=1, customer=None):
    if not doctype in ["Shop Invoice", "Shop Item", "Order Customer"]:
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

    elif doctype in ["Shop Customer", "Order Customer"]:
        data = None
        if doctype == "Shop Customer":
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
                        WITH s AS (
                            SELECT name, warehouse, company, branch, currency, sales_person
                            FROM tabShop
                            WHERE name = %(shop)s
                        ),
                        candidates AS (
                            SELECT c.*
                            FROM tabCustomer c
                            WHERE c.name = %(name)s
                                OR c.customer_name LIKE CONCAT('%%', %(name)s, '%%')
                        ),
                        last_so_pl AS (
                        SELECT so.customer,
                                so.custom_shop,
                                so.selling_price_list,
                                ROW_NUMBER() OVER (PARTITION BY so.customer, so.custom_shop
                                                    ORDER BY so.transaction_date DESC, so.name DESC) AS rn
                        FROM `tabSales Order` so
                        WHERE so.custom_shop = %(shop)s
                            AND so.docstatus = 1
                            AND so.status IN ('To Deliver and Bill', 'To Bill', 'To Deliver')
                        )
                        SELECT
                        ROW_NUMBER() OVER (ORDER BY c.name) AS id,
                        c.name,
                        CASE WHEN c.name <> c.customer_name
                            THEN CONCAT(c.name, ' ', c.customer_name)
                            ELSE c.customer_name END AS customer_name,
                        c.customer_name AS description,
                        c.mobile_no  AS mobile,
                        c.email_id   AS email,
                        c.image,
                        0 AS balance,
                        c.creation   AS created_at,
                        c.modified   AS updated_at,
                        c.territory,
                        s.warehouse, s.company, s.branch, s.currency, s.sales_person,
                        COALESCE(pl.selling_price_list, c.default_price_list) AS selling_price_list,
                        c.tax_id,
                        c.custom_b2c,
                        c.custom_other_buying_id,
                        c.nfc_only,
                        c.signature
                        FROM candidates c
                        CROSS JOIN s
                        LEFT JOIN last_so_pl pl
                        ON pl.customer = c.name AND pl.custom_shop = s.name AND pl.rn = 1
                        WHERE EXISTS (
                                SELECT 1 FROM `tabShop Territory` t
                                WHERE t.parent = s.name AND t.territory = c.territory
                            )
                        OR EXISTS (
                                SELECT 1 FROM `tabSales Order` so
                                WHERE so.customer = c.name
                                AND so.custom_shop = s.name
                                AND so.docstatus = 1
                                AND so.status IN ('To Deliver and Bill','To Bill','To Deliver')
                            )
                        ORDER BY c.name;
                    """,{"shop":shop, "name":name}, as_dict=1
                )
        else:
            data = frappe.db.sql(
                """
                SELECT (SELECT COUNT(*) + 1 FROM tabCustomer t2 WHERE t2.name <= t1.name) AS id,
                t1.name,CASE WHEN t1.name <> t1.customer_name THEN CONCAT(t1.name,' ',t1.customer_name) ELSE t1.customer_name END AS customer_name,
                t1.customer_name as description, 
                t1.mobile_no as mobile,t1.email_id as email,t1.image, 0 as balance, t1.creation as created_at, t1.modified as updated_at,
                t1.territory, t1.warehouse, t1.company, t1.branch, t1.currency, t1.sales_person, t1.selling_price_list, t1.tax_id,
                t1.custom_b2c, t1.tax_id, t1.custom_other_buying_id, t1.nfc_only, t1.signature
                FROM (
                    SELECT c.*, s.warehouse, s.company, s.branch, s.currency, s.sales_person, so.selling_price_list 
                    FROM tabShop s  CROSS JOIN tabCustomer c INNER JOIN `tabSales Order` so ON so.customer = c.name AND so.custom_shop = s.name
                    WHERE s.name = %(shop)s AND c.name = %(name)s AND so.status IN ('To Deliver and Bill', 'To Bill', 'To Deliver') AND so.docstatus = 1
                ) AS t1
                """,{"shop":shop, "name":name}, as_dict=1
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
        limit = 100
        if customer:
            customer_price_list = frappe.db.get_value("Customer", customer, "default_price_list")
            data = frappe.db.sql(
                """
                SELECT p.name as id, p.product_code, p.title, p.unit_type, p.unit_value, p.brand, p.category_ids, p.purchase_price, 
                    ip.price_list_rate as selling_price, p.discount_type, p.discount, p.tax, SUM(b.actual_qty) as quantity, 
                    p.image, p.order_count, p.supplier_id, p.company_id, p.creation as createdAt, p.modified as updatedAt
                FROM `tabShop` s 
                CROSS JOIN `tabShop Product` p 
                INNER JOIN tabBin b ON p.product_code = b.item_code AND s.warehouse = b.warehouse
                INNER JOIN tabItem i ON i.name = p.product_code
                INNER JOIN `tabItem Price` ip ON ip.item_code = p.product_code AND ip.price_list = %(price_list)s
                WHERE i.disabled = 0 AND b.actual_qty > 0 AND s.name = %(shop)s
                GROUP BY p.name, p.product_code, p.title, p.unit_type, p.unit_value, p.brand, p.category_ids, p.purchase_price, 
                    ip.price_list_rate, p.discount_type, p.discount, p.tax, p.image, p.order_count, p.supplier_id, p.company_id, 
                    p.creation, p.modified
                LIMIT %(limit)s OFFSET %(offset)s
                """, {
                    "shop": shop,
                    "limit": int(limit),
                    "offset": int(offset),
                    "price_list": customer_price_list
                }, as_dict=1
            )
        else:
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
    # ...existing code...

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


@frappe.whitelist(allow_guest=True)
def create_order(**request_dict):
    customer = ""
    # Si aucun argument passé (appel API direct), lire depuis le corps de la requête
    if not request_dict:
        raw_data = frappe.request.data
        if raw_data:
            request_dict = frappe.parse_json(raw_data.decode("utf-8"))
            #customer = request_dict.get('customer')
        else:
            frappe.throw("No order data provided.")
    #else:
    #    customer = "AC00000000"

    
    cart_data = request_dict.get("cart")
    customer = request_dict.get("customer") or "AC00000000"
    #warehouse = request_dict.get("set_warehouse")
    transaction_id = request_dict.get("transaction_id")
    payment_method = request_dict.get("payment_method")
    invoice_id = request_dict.get("invoice_id")
    payment_gateway = request_dict.get("payment_gateway")
    paid_at = request_dict.get("paid_at")
    payment_status = request_dict.get("payment_status")
    custom_latitude = request_dict.get("coustome_latitude")
    custom_longitude = request_dict.get("coustome_longitude")

    taxes_and_charges = request_dict.get("taxes_and_charges")
    taxes = request_dict.get("taxes")

    if not cart_data or not customer:
        frappe.log_error("Missing cart or customer_name", "Create Order Error")
        return None
        #frappe.throw("Missing cart or customer_name")

    selling_price_list = frappe.db.get_value("Customer",customer,"default_price_list")

    order_details = []
    for i in cart_data:
        details = frappe._dict({
            "doctype": "Sales Order Item",
            "item_code": i["item_code"],
            "qty": i["quantity"],   
            #"warehouse": warehouse         
        })
        order_details.append(details)

    args = frappe._dict(
        {
            "doctype": "Sales Order",
            "customer": customer,
            "transaction_date": frappe.utils.getdate(),
            "delivery_date": frappe.utils.getdate(),
            "selling_price_list": selling_price_list,
            "items": order_details,
            "set_warehouse": request_dict.get("set_warehouse"),
            "branch": "HAIL",
            "taxes_and_charges": taxes_and_charges,
            "taxes": taxes,
            "custom_latitude": custom_latitude,
            "custom_longitude": custom_longitude
        }
    )
    if transaction_id != None:
        args.update({
            "transaction_id": transaction_id,
            "payment_method": payment_method,
            "invoice_id": invoice_id,
            "payment_gateway": payment_gateway,
            "paid_at": paid_at,
            "payment_status": payment_status,
        })

    #frappe.throw(frappe.as_json(args))
    frappe.log_error(frappe.as_json(args), "Create Order Data")
    old_user = frappe.session.user
    try:
        frappe.set_user("Administrator")
        sale = frappe.get_doc(args)
        #sale.ignore_pricing_rule = 1
        sale.insert(ignore_permissions=True)
        frappe.db.commit()
        # ✅ preuve immédiate
        if not frappe.db.exists("Sales Order", sale.name):
            frappe.log_error(f"Not found after insert: {sale.name}", "Create Order Debug")
            frappe.throw("Sales Order not found after insert (rollback).")

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Create Order Insert Failed")
        frappe.throw("Error creating order.")
        raise
    finally:
        frappe.set_user(old_user)
        
    return sale



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

        #customer_group = frappe.db.get_value("Customer", doc.get('customer'), "customer_group")
        customer = doc.get('customer')
        promo_data = get_promotion(doc.get('set_warehouse'), item.get('item_code'), customer, max_qty)

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
def create_invoice_old():
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
    is_order = 0
    
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

    #if request_dict.get('is_order'):
    #    is_order = request_dict.get('is_order')

    #order_doc = None
    #if bool(is_order):
    #    order_name = cart_data[0].order_id
    #    order_doc = frappe.get_doc("Sales Order", order_name)
    #    selling_price_list = order_doc.selling_price_list

    shop_doc = frappe.get_doc("Shop", shop)
    pending_amount = get_pending_amount(shop_doc)
        
    if payment_type == "Credit":
        meta = get_meta("Customer")
        if meta.get_field("custom_customer_account_type"):
            custom_customer_account_type = frappe.db.get_value("Customer", customer,"custom_customer_account_type")
            if custom_customer_account_type != "CONTRACT CUSTOMER":
                if not shop_doc.unlimited_credit : 
                    
                    total_pending = flt(pending_amount) + flt(total_amount) * 0.15
                    if flt(shop_doc.credit_limit) < total_pending :
                        frappe.throw("Your pending is {0} is more than your credit limit {1}. You can not credit to this customer!").format(str(total_pending), str(shop_doc.credit_limit))
        else:
            if not shop_doc.unlimited_credit : 
                total_pending = flt(pending_amount) + flt(total_amount) * 0.15
                if flt(shop_doc.credit_limit) < total_pending :
                    frappe.throw("Your pending is {0} is more than your credit limit {1}. You can not credit to this customer!").format(str(total_pending), str(shop_doc.credit_limit))
        
        outstanding_amt = get_customer_outstanding(
            customer, company, ignore_outstanding_sales_order=True
        )
        credit_limit = get_credit_limit(customer, company)
        total_out = flt(outstanding_amt) + flt(total_amount) * 0.15
        bal = flt(credit_limit) - total_out
        if bal < 0 :
            frappe.throw("The credit limit is {0}. The outstanding amount is {1}. You can no more add invoices!").format(str(credit_limit), str(total_out))

    invoice_details = []
    temp_batches = []
    for i in cart_data:
        if i["quantity"] == 0:
            continue
        
        max_qty = i["quantity"]

        #customer_group = frappe.db.get_value("Customer",customer, "customer_group")
        #promo_data = get_promotion(warehouse, i["product_code"], customer_group, max_qty)
        promo_data = get_promotion(warehouse, i["product_code"], customer, max_qty)

        details, temp_batches = get_item_batches(warehouse, i["product_code"], promo_data, branch, max_qty,False, i["id"], i["price"])        
        invoice_details.extend(details)
        #for d in details:
        #    invoice_details.append(d)

        if len(promo_data) > 0:
            for p in promo_data:
                if p["price_or_product_discount"] == "Product" and p["total_free_qty"] > 0:
                    if i["product_code"] == p["free_item"]:
                        details, temp_batches2  = dispatch_by_batch(temp_batches,[], branch, p["free_item"], p["total_free_qty"], True, i["id"], 0)
                        invoice_details.extend(details)
                    else:
                        details, temp_batches = get_item_batches(warehouse, p["free_item"], [], branch, p["total_free_qty"], True, i["id"], 0) 
                        invoice_details.extend(details)
                #elif p["price_or_product_discount"] == "Price":
                #    details, temp_batches2  = dispatch_by_batch(temp_batches,[], branch, p["free_item"], p["total_free_qty"], True)
                #    invoice_details.extend(details) 

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

            tax_list = frappe.db.sql(
                """
                SELECT *
                FROM `tabSales Taxes and Charges`
                WHERE parent = 'KSA VAT 15% - AHW'
                """, as_dict=1
            )

            tax = frappe._dict({
                "charge_type": tax_list[0].charge_type,
                "account_head": tax_list[0].account_head,
                "description": tax_list[0].description,
                "rate": tax_list[0].rate,
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

            #if order_doc != None:
            #    for c in cart_data:
            #        order_item = next((x for x in order_doc.items if x.item_code == c["product_code"] and x.is_free_item == c["is_free_item"]), None)

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
                shop_doc.peding_amount = pending_amount + flt(sale.grand_total)
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

@frappe.whitelist()
def get_orders(customer):

    data = frappe.db.sql(
        """
        SELECT t.id, - t.id AS product_id, t.item_code, t.qty, t.rate, t.amount, t.is_free_item, t.payment_gateway as gateway
        FROM
            (SELECT ROW_NUMBER() OVER() AS id, p.name AS product_id, i.item_code, SUM(i.qty - i.delivered_qty) AS qty, i.rate, SUM(i.amount) AS amount, i.is_free_item,
            o.payment_gateway
            FROM `tabSales Order` o INNER JOIN `tabSales Order Item` i ON i.parent = o.name INNER JOIN `tabShop Product` p ON p.product_code = i.item_code
            WHERE o.customer = %(customer)s AND o.docstatus = 1 AND i.delivered_qty < i.qty
            GROUP BY p.name, i.item_code, i.qty, i.rate, i.is_free_item, o.payment_gateway) AS t
        """, {"customer": customer}, as_dict=1
    )
        #Union Commandes par le territory a qui appartient le liste de prix du client itinérant
    return frappe._dict({
        "total": len(data),
        "limit": 0,
        "offset": 0,
        "order": data,
    })

@frappe.whitelist()
def get_orders_by_shop(shop):

    data = frappe.db.sql(
        """
        SELECT t.id, - t.id AS product_id, t.item_code, t.qty, t.rate, t.amount, t.is_free_item, t.customer,t.custom_shop, t.order_id, t.net_total, 
        t.customer_name, t.order_item_id, t.payment_gateway as gateway
        FROM
            (SELECT ROW_NUMBER() OVER() AS id, p.name AS product_id, i.item_code, i.qty - i.delivered_qty AS qty, i.rate, i.amount, 
                i.is_free_item, o.customer, o.custom_shop, o.name as order_id, o.net_total, o.customer_name, i.name AS order_item_id,
                o.payment_gateway
            FROM `tabSales Order` o INNER JOIN `tabSales Order Item` i ON i.parent = o.name INNER JOIN `tabShop Product` p ON p.product_code = i.item_code
            WHERE o.docstatus = 1 AND i.delivered_qty < i.qty AND o.custom_shop = %(shop)s AND o.status NOT IN ('Closed', 'Completed')
            ) AS t
        """, {"shop": shop}, as_dict=1
    )
        #Union Commandes par le territory a qui appartient le liste de prix du client itinérant
    return frappe._dict({
        "total": len(data),
        "limit": 0,
        "offset": 0,
        "order": data,
    })

@frappe.whitelist()
def get_orders_by_shop_and_customer(shop, customer):

    data = frappe.db.sql(
        """
        SELECT t.id, - t.id AS product_id, t.item_code, t.qty, t.rate, t.amount, t.is_free_item, t.customer,t.custom_shop, t.order_item_id, t.payment_gateway as gateway
        FROM
            (SELECT ROW_NUMBER() OVER() AS id, p.name AS product_id, i.item_code, i.qty - i.delivered_qty AS qty, i.rate, i.amount, 
                i.is_free_item, o.customer, o.custom_shop, i.name AS order_item_id, o.payment_gateway
            FROM `tabSales Order` o INNER JOIN `tabSales Order Item` i ON i.parent = o.name INNER JOIN `tabShop Product` p ON p.product_code = i.item_code
            WHERE o.docstatus = 1 AND i.delivered_qty < i.qty AND o.custom_shop = %(shop)s AND o.customer = %(customer)s
            ) AS t
        """, {"shop": shop, "customer": customer}, as_dict=1
    )
        #Union Commandes par le territory a qui appartient le liste de prix du client itinérant
    return frappe._dict({
        "total": len(data),
        "limit": 0,
        "offset": 0,
        "order": data,
    })

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

@frappe.whitelist()
def get_branch_name_from_geofence(latitude, longitude):
    geofence_price_list = frappe.db.get_single_value("Shop Settings", "geofence_price_list")
    if bool(geofence_price_list):
        if not latitude or not longitude:
            frappe.throw("Latitude and longitude are required.")

        # Fetch geofence data from ERPNext
        branches = frappe.get_all('Branch', fields=['name', 'custom_geofence'])

        point = Point(latitude, longitude)

        for b in branches:
            if not b.custom_geofence:
                continue  # Ignore les branches sans géofence
            # The geofence_coordinates should be stored as a list of tuples, e.g., [(41.6500, 27.5400), (41.6600, 27.5500), ...]
            geofence = json.loads(b.custom_geofence)
            geometry = geofence.get("geometry")
            coords=[]
            if not isinstance(geometry, dict):
                coords = geofence["features"][0]["geometry"]["coordinates"][0]
            else:
                coords = geofence["geometry"]["coordinates"][0]
            #print(str(coords))

            # Create the polygon for the current geofence
            polygon = Polygon(coords)

            # Check if the point is inside the polygon
            if polygon.contains(point):
                #return b['name']  # Return the name of the city (e.g., 'Hail')
                item_prices = []
                branch = b['name']
                if branch:
                    item_prices = frappe.db.sql(
                        """
                        SELECT ip.item_code, ip.price_list_rate, i.image
                        FROM `tabPrice List` pl 
                        INNER JOIN `tabItem Price` ip ON ip.price_list = pl.name
                            INNER JOIN tabItem i ON i.name = ip.item_code
                        WHERE pl.custom_branch = %(branch)s AND ip.price_list LIKE '%%APP CUSTOMERS%%'
                        """, {"branch": branch}, as_dict=1
                    )
                    return item_prices or []

        return None
        #return _("We do not serve this area")


@frappe.whitelist()
def get_branch_name_by_location(latitude, longitude):
    geofence_price_list = frappe.db.get_single_value("Shop Settings", "geofence_price_list")
    if bool(geofence_price_list):
        if not latitude or not longitude:
            frappe.log_error("Latitude and longitude are required.", "Geofence Error")
            frappe.throw("Latitude and longitude are required.")

        # Fetch geofence data from ERPNext
        branches = frappe.get_all('Branch', fields=['name', 'custom_geofence'])

        point = Point(latitude, longitude) #A Uniformiser

        for b in branches:
            if not b.custom_geofence:
                continue  # Ignore les branches sans géofence
            # The geofence_coordinates should be stored as a list of tuples, e.g., [(41.6500, 27.5400), (41.6600, 27.5500), ...]
            geofence = json.loads(b.custom_geofence)
            geometry = geofence.get("geometry")
            coords=[]
            if not isinstance(geometry, dict):
                coords = geofence["features"][0]["geometry"]["coordinates"][0]
            else:
                coords = geofence["geometry"]["coordinates"][0]
            #print(str(coords))

            # Create the polygon for the current geofence
            polygon = Polygon(coords)

            # Check if the point is inside the polygon
            if polygon.contains(point):
                #return b['name']  # Return the name of the city (e.g., 'Hail')
                return b['name']
            
    frappe.log_error("No branch found for the given location.", "Geofence Error")
    return None


@frappe.whitelist()
def get_closest_location(latitude, longitude):
    closest_location_price_list = frappe.db.get_single_value("Shop Settings", "closest_location_price_list")
    if bool(closest_location_price_list):
        if not latitude or not longitude:
            frappe.log_error("Latitude and longitude are required.", "Closest Location Error")
            frappe.throw("Latitude and longitude are required.")

        item_prices = frappe.db.sql(
            """
            SELECT ip.item_code, ip.price_list_rate, i.image
            FROM (
                SELECT name,
                        (6371 * ACOS(
                            COS(RADIANS(%(latitude)s)) * COS(RADIANS(custom_latitude)) *
                            COS(RADIANS(custom_longitude) - RADIANS(%(longitude)s)) +
                            SIN(RADIANS(%(latitude)s)) * SIN(RADIANS(custom_latitude))
                        )) AS distance
                FROM `tabPrice List` 
                WHERE custom_latitude IS NOT NULL AND custom_longitude IS NOT NULL
                ORDER BY distance ASC
                LIMIT 1
            ) AS closest
            INNER JOIN `tabItem Price` ip ON ip.price_list = closest.name
                INNER JOIN tabItem i ON i.name = ip.item_code
            """, {"latitude": latitude, "longitude": longitude}, as_dict=1
        )
        if not item_prices:
            frappe.log_error("No closest location found for the given coordinates.", "Closest Location Error")
            
        return item_prices or []


@frappe.whitelist()
def get_app_defaut_price_list():
    use_default_price_list = frappe.db.get_single_value("Shop Settings", "use_default_price_list")
    if bool(use_default_price_list):
        price_list = frappe.db.get_single_value("Shop Settings", "price_list")
        item_prices = frappe.db.sql(
            """
            SELECT DISTINCT ip.item_code, ip.price_list_rate, i.image
            FROM `tabItem Price` ip INNER JOIN tabItem i ON i.name = ip.item_code
            WHERE ip.price_list = %(price_list)s
            """, {"price_list": price_list}, as_dict=1
        ) 

        return item_prices or []

    else:
        frappe.log_error("Default price list is not enabled.", "Default Price List Error")
        return []  
        
    


@frappe.whitelist()
def get_price_list(area="UNKWON_AREA", latitude=0, longitude=0):
    swap_var = latitude
    latitude = longitude
    longitude = swap_var
    item_prices = (
        get_branch_name_from_geofence(latitude, longitude)
        or get_closest_location(latitude, longitude)
        or get_app_defaut_price_list()
    )

    # Si toujours rien, on lève une exception
    if not item_prices:
        frappe.throw(_("We do not serve this area"))

    return item_prices    


#def rename_customer_address(new_name, address_name):
#    if new_name and address_name:
#        # Attempt to rename the address to match the customer's name
#        try:
#            frappe.rename_doc("Address", address_name, new_name, force=True)
#            frappe.db.commit()
#        except Exception as e:
#            frappe.log_error(e, _("Error renaming Address {0}").format(address_name))


def rename_customer_address(new_name, old_name):
    if new_name and old_name:
        try:
            # Renommer directement dans tabAddress
            frappe.db.sql("""
                UPDATE `tabAddress` SET name = %s WHERE name = %s
            """, (new_name, old_name))

            # Mettre à jour les références dans tabDynamic Link (si l’adresse est liée à d'autres documents)
            frappe.db.sql("""
                UPDATE `tabDynamic Link` SET parent = %s 
                WHERE parenttype = 'Address' AND parent = %s
            """, (new_name, old_name))

            frappe.db.commit()
        except Exception as e:
            frappe.log_error(e, _("Fast rename failed for Address {0}").format(old_name))



@frappe.whitelist()
def create_address():
    request_data = frappe.request.data
    request_data_str = request_data.decode('utf-8')
    request_dict = frappe.parse_json(request_data_str)
    try:
        # Extracting address data from the input
        address_data = request_dict.get("data", {})
        
        # Check that required fields are present
        if not address_data.get("links") or not address_data["links"][0].get("link_name"):
            frappe.throw(_("Customer link name is required to create the address."))
        
        # Create the Address document
        address_doc = frappe.get_doc({
            "doctype": "Address",
            "address_title": address_data.get("address_title"),
            "address_line1": address_data.get("address_line1"),
            "address_line2": address_data.get("address_line2"),
            "city": address_data.get("city"),
            "state": address_data.get("state"),
            "pincode": address_data.get("pincode"),
            "country": "Saudi Arabia", #address_data.get("country"),
            "phone": address_data.get("phone"),
            "custom_area": address_data.get("custom_area"),
            "custom_longitude": address_data.get("custom_longitude"),
            "custom_latitude": address_data.get("custom_latitude"),
            "email_id": address_data.get("email_id"),
            "links": address_data.get("links")
        })
        
        # Insert the document into the database
        address_doc.insert()
        frappe.db.commit()

        customer_name = address_data["links"][0].get("link_name")
        code = 100 + int(address_doc.custom_code)
        address_name = customer_name + "_" + str(code)[1:]
        
        rename_customer_address(address_name, address_doc.name)

        return {"status": "success", "message": _("Address created successfully"), "address_name": address_name}
    
    except Exception as e:
        frappe.log_error(e, _("Error creating Address"))
        return {"status": "error", "message": str(e)}


def create_address_2(address_data, customer_name):
    try:                
        # Create the Address document
        address_doc = frappe.get_doc({
            "doctype": "Address",
            "address_title": address_data.get("address_title"),
            "address_line1": address_data.get("address_line1"),
            "city": address_data.get("city"),
            "state": address_data.get("state"),
            "pincode": address_data.get("pincode"),
            "country": "Saudi Arabia", #address_data.get("country"),
            "phone": address_data.get("phone"),
            "custom_area": address_data.get("custom_area"),
            "custom_longitude": address_data.get("custom_longitude"),
            "custom_latitude": address_data.get("custom_latitude"),
            "email_id": address_data.get("email_id"),
            "links": [
                {
                    "link_doctype": "Customer",
                    "link_name": customer_name
                }
            ]
        })
        
        # Insert the document into the database
        address_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        code = 100 + int(address_doc.custom_code)
        address_name = customer_name + "_" + str(code)[1:]
        
        rename_customer_address(address_name, address_doc.name)

        return {"status": "success", "message": _("Address created successfully"), "address_name": address_name}
    
    except Exception as e:
        frappe.log_error(e, _("Error creating Address"))
        return {"status": "error", "message": str(e)}



@frappe.whitelist()
def zzz_create_user_and_customer():
    request_data = frappe.request.data
    request_data_str = request_data.decode('utf-8')
    request_dict = frappe.parse_json(request_data_str)
    # Accessing the inner data dictionary
    data = request_dict.get("data", {})
    try:
        # Extracting address data from the input
        email = data.get("email")
        first_name = data.get("first_name")
        last_name = data.get("last_name", "")
        password = data.get("password")
        mobile_no = data.get("mobile_no")
        address_data = data.get("address_data", {})

        # Step 1: Create the User
        user_doc = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "new_password": password,
            "mobile_no": mobile_no,
            "send_welcome_email": 0,
            "roles": [
                {"role": "Customer"},
                {"role": "Sales User"},
                {"role": "APP CUSTOMER"}
            ]
        })
        user_doc.insert(ignore_permissions=True)
        #user_doc.new_password = password
        #user_doc.save()
        #print(str(user_doc.flags.in_insert))
        #user_doc.email_new_password(password)
        frappe.db.commit()
        
        #update_password(user_doc.name, password)
        
        print("User created successfully.")

        # Step 2: Generate API Secret (Private Key) for the User
        private_key = generate_keys(user_doc.name)["api_secret"]
        print(f"Private Key generated: {private_key}")

        # Step 3: Get the API Key (Public Key)
        #public_key = user_doc.api_key
        doc = frappe.get_doc("User", email)
        public_key = doc.api_key
        print(f"Public Key retrieved: {public_key}")

        # Step 4: Get the Highest Existing Customer Code
        highest_customer = frappe.get_all(
            "Customer",
            filters={"customer_group": "App Customer Group"},
            fields=["name"],
            order_by="name desc",
            limit_page_length=1
        )
        
        highest_customer_code = highest_customer[0].name if highest_customer else "AC00000000"
        new_customer_code = f"AC{int(highest_customer_code[2:]) + 1:08d}"
        print(f"New customer code generated: {new_customer_code}")

        # Step 5: Create the Customer Using the New Customer Code
        customer_doc = frappe.get_doc({
            "doctype": "Customer",
            "name": new_customer_code,
            "custom_customer_code": new_customer_code,
            "customer_name": f"{first_name} {last_name}",
            "email_id": email,
            "customer_group": "App Customer Group",
            "territory": "All Territories",
            "customer_type": "Individual"
        })
        customer_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        frappe.msgprint("Customer created successfully.")

        if address_data:
            create_address_2(address_data, customer_doc.name)

        frappe.db.commit()

        # Return all keys and customer information
        return {
            "user_email": email,
            "public_key": public_key,
            "private_key": private_key,
            "customer_code": new_customer_code
        }

    except Exception as e:
        frappe.log_error(f"Error creating user and customer: {str(e)}", "User and Customer Creation")
        return {"error": "An error occurred during the creation process", "details": str(e)}

def is_valid_email(email):
    """Validate if the input is a valid email address."""
    #email_regex = r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"
    if not email:
        return False
    
    email = email.strip().lower()
    email_regex = r"^\+?[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$"
    return re.match(email_regex, email) is not None

def normalize_login_email(login_id: str, mobile_domain: str = "mobile.com") -> str:
    """
    Normalise le login en email.
    - Email => inchangé
    - Numéro (avec +, espaces, tirets) => "+9660501038693@mobile.com"
    """
    if not login_id:
        return ""

    s = login_id.strip()

    # Déjà un email
    if "@" in s:
        return s.lower()

    # Nettoyage léger: enlève espaces / tirets / parenthèses
    cleaned = re.sub(r"[\s\-\(\)]", "", s)

    # Si ça ressemble à un numéro (optionnel + puis chiffres)
    if re.fullmatch(r"\+?\d{6,20}", cleaned):
        return f"{cleaned}@{mobile_domain}".lower()

    # Sinon: on retourne tel quel (ou tu peux décider de lever une erreur)
    return s.lower()

@frappe.whitelist( allow_guest=True)  # Permet l'accès aux utilisateurs non connectés
def login():
    request_data = frappe.request.data
    request_data_str = request_data.decode('utf-8')
    request_dict = frappe.parse_json(request_data_str)

     # Accessing the inner data dictionary
    data = request_dict.get("data", {})
    
    try:
        frappe.log_error("Login Data", str(data))
        # Extracting login credentials from the input
        login_id = data.get("email")
        login_id = normalize_login_email(login_id) 
        frappe.log_error("Login Attempt", f"Login attempt for {login_id}")
        password = data.get("password")

        # Determine if the login_id is an email or phone
        if is_valid_email(login_id):
            email = frappe.db.get_value("User", {"email": login_id}, "name")
            if not email:
                frappe.log_error(f"Login failed for email: {login_id}", "Login Error")
                frappe.throw(frappe._(f"The email {login_id} does not exist."), frappe.AuthenticationError)
        else:
            login_id = login_id.split("@")[0]
            email = frappe.db.get_value("User", {"mobile_no": login_id}, "name")
            if not email:
                frappe.log_error(f"Login failed for phone number: {login_id}", "Login Error")
                frappe.throw(frappe._(f"The phone number {login_id} does not exist."), frappe.AuthenticationError)

        pwd = frappe.db.get_single_value('Abar Settings', 'app_user_password')

        #if not check_password(email, password, delete_tracker_cache=False):
        if password != pwd:
            return {"error": "Login Issue", "details": "Your credential does not exist"}

        # Step 1: Generate API Secret (Private Key) for the User
        #private_key = generate_keys(email)["api_secret"]

        old_user = frappe.session.user
        try:
            frappe.set_user("Administrator")  # ou un user technique System Manager
            private_key = generate_keys(email)["api_secret"]
        finally:
            frappe.set_user(old_user)
        
        # Step 2: Get the User Info
        user_doc = frappe.get_doc("User",email)

        # Step 3: Get the API Key (Public Key)
        cust_doc = frappe.get_doc("Customer",{"email_id":email})

        # Step 4: Create the Customer Using the New Customer Code
        frappe.set_user("Administrator")  # ou un user technique System Manager
        addr_list = frappe.db.get_list("Address",
            fields=["name", "address_line1", "address_line2", "address_in_arabic", "city", "county", "state", "country","pincode", "email_id", "phone", "fax"],
            filters={"name":["LIKE", cust_doc.name +"%"]})
        frappe.set_user(old_user)

        # Return all keys and customer information
        return {
            "first_name": user_doc.first_name,
            "last_name": user_doc.last_name,
            "public_key": user_doc.api_key,
            "private_key": private_key,
            "customer_code": cust_doc.name,
            "addresses": addr_list,
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "User and Customer Creation")
        return {"error": "An error occurred during the login process", "details": str(e)}


@frappe.whitelist()
def get_valid_advertisements():
    try:
        # Get today's date
        today = getdate()

        # Fetch all valid advertisements
        #advertisements = frappe.db.get_list(
        #    "App Advertisement",
        #    fields=[
        #        "name", "text", "from_date", "to_date", "image", "item",
        #        "promotion_type", "promotion_rate", "gift", "gift_type",
        #        "calculation", "gift_rate"
        #    ],
        #    filters={
        #        "docstatus": 1,
        #        "from_date": ["<=", today],
        #        "to_date": [">=", today]
        #    },
        #    order_by="from_date"
        #)

        advertisements = frappe.db.sql(
        """
        SELECT *
        FROM `tabApp Advertisement` 
        WHERE docstatus = 1 AND from_date <= %s AND to_date >= %s
        """, (today,today), as_dict=1
    )

        # Return the list of valid advertisements
        return {"status": "success", "advertisements": advertisements}

    except Exception as e:
        frappe.log_error(f"Error fetching advertisements: {str(e)}", "Advertisement Error")
        return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)  # Permet l'accès aux utilisateurs non connectés
def request_account_deletion(email):
    """
    API pour demander la suppression des données personnelles.
    L'utilisateur envoie son email, et une demande est enregistrée en base de données.
    """

    # Vérifier si l'email existe dans le système
    user = frappe.db.exists("User", {"email": email})
    if not user:
        frappe.local.response.http_status_code = 404
        return {"status": "error", "message": _("Email not found")}

    # Vérifier si une demande est déjà en cours
    existing_request = frappe.get_all(
        "Personal Data Deletion Request",
        filters={"email": email, "status": ["not in", ["Deleted"]]},
        fields=["name"]
    )
    if existing_request:
        frappe.local.response.http_status_code = 400
        return {"status": "error", "message": _("A request is already pending.")}

    # Créer une demande de suppression
    doc = frappe.get_doc({
        "doctype": "Personal Data Deletion Request",
        "email": email,
        "status": "Pending Approval",
        #"request_date": now_datetime()
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"status": "success", "message": _("Deletion request submitted successfully. Please check your email for verification.")}


@frappe.whitelist()
def set_primary_address(customer, address):
    # Trouver tous les liens dynamiques de type "Customer"
    dynamic_links = frappe.get_all(
        "Dynamic Link",
        filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Address"},
        fields=["parent"]
    )

    # Réinitialiser toutes les adresses liées comme non principales
    for link in dynamic_links:
        frappe.db.set_value("Address", link.parent, "is_primary_address", 0)

    # Définir l'adresse sélectionnée comme principale
    frappe.db.set_value("Address", address, "is_primary_address", 1)

    frappe.db.commit()

@frappe.whitelist()
def get_primary_address(customer):
    links = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Customer",
            "link_name": customer,
            "parenttype": "Address"
        },
        fields=["parent"]
    )

    for link in links:
        address_doc = frappe.get_doc("Address", link.parent)
        if address_doc.is_primary_address:
            return {
                "name": address_doc.name,
                "address_line1": address_doc.address_line1,
                "city": address_doc.city,
                "country": address_doc.country
            }

    frappe.throw(_("No primary address found for customer {0}").format(customer))


#///////////////////////////////////////////////////////////////////////////////////////////////////////
def select_shop_on_submit(doc, method):
    if not doc.selling_price_list:
        return

    # Get location from Price List
    price_list = frappe.get_doc("Price List", doc.selling_price_list)
    lat = price_list.get("custom_latitude")
    lon = price_list.get("custom_longitude")

    if not lat or not lon:
        return
        
    if lat > 0:
        # Find shops at the same location, sorted by oldest assignment
        shops = frappe.get_all(
            "Shop",
            filters={
                "custom_latitude": lat,
                "custom_longitude": lon
            },
            fields=["name", "custom_last_assigned_date"],
            order_by="IFNULL(custom_last_assigned_date, '1900-01-01') ASC"
        )

        if not shops:
            return

        selected_shop = shops[0]  # Least recently assigned

        # Set selected shop on Sales Order (custom field)
        doc.db_set("custom_shop", selected_shop.name)

        # Update the shop's last assignment date
        frappe.db.set_value("Shop", selected_shop.name, "custom_last_assigned_date", now_datetime())


#/////////////////////////////////////////NEW APP //////////////////////////////////////////////////////////////////////
# api/invoice_api.py

from mobilepos.utils.invoice_creation import (
    validate_credit_limit,
    parse_invoice_request,
    build_invoice_items,
    generate_sales_invoice,
    update_sales_order_items
)


def handle_payment_and_visit(sale, shop_doc, payment_type, customer, branch, shop, visit_name):
    if visit_name:
        visit = frappe.get_doc("Shop Visit", visit_name)
        visit.append('details', {
            "document_type": "Sales Invoice",
            "document_name": sale.name,
            "posting_date": sale.creation,
            "amount": sale.grand_total,
        })
        visit.save()

    signature = frappe.db.get_value("Customer", customer, "signature")
    if signature == 0: 
        if payment_type == "Cash":
            pay_name = create_pos_cash_payment_invoice(shop, shop_doc.company, customer, sale.name, branch, sale.grand_total, visit_name)
            add_payment_to_invoice(pay_name, sale)
            sale.save()

        sale.submit()
        shop_doc.peding_amount = flt(get_pending_amount(shop_doc)) + flt(sale.grand_total)
        shop_doc.save()


@frappe.whitelist()
def create_invoice():
    request_data = frappe.request.data
    request_dict = frappe.parse_json(request_data.decode("utf-8"))
    parsed = parse_invoice_request(request_dict)

    shop_doc = frappe.get_doc("Shop", parsed["shop"])
    pending_amount = get_pending_amount(shop_doc)

    if parsed["payment_type"] == "Credit":
        if parsed["is_order"] == 0:
            validate_credit_limit(parsed["customer"], parsed["company"], shop_doc, parsed["total_amount"])
        else:
            frappe.throw("App Users cannot get credit")

    try:
        invoice_details, cart_items = build_invoice_items(
            parsed["cart_data"], parsed["warehouse"], parsed["branch"], parsed["customer"], is_order=bool(parsed["is_order"])
        )

        if bool(parsed["is_order"]):
            order_id = parsed["cart_data"][0]["order_id"]
            selling_price_list = frappe.db.get_value("Sales Order", order_id, "selling_price_list")
        else:
            selling_price_list = parsed["selling_price_list"]
        args = frappe._dict({
            "doctype": "Sales Invoice",
            "customer": parsed["customer"],
            "company": parsed["company"],
            "branch": parsed["branch"],
            "set_warehouse": parsed["warehouse"],
            "update_stock": 1,
            "sales_reconciliation": parsed["sales_person"],
            "selling_price_list": selling_price_list ,
            "shop": parsed["shop"],
            "items": invoice_details,
            "payment_type": parsed["payment_type"],
        })

        sales_team = frappe._dict({
            "sales_person": parsed["sales_person"],
            "allocated_percentage": 100,
            "doctype": "Sales Team",
        })
        if sales_team:
            args.update({"sales_team": [sales_team],})

        tax_list = frappe.db.sql("""
            SELECT stc.*
            FROM `tabSales Taxes and Charges Template` tct
            JOIN `tabSales Taxes and Charges` stc ON stc.parent = tct.name
            WHERE tct.company = %s AND tct.is_default = 1 AND tct.disabled = 0
        """, (parsed["company"],), as_dict=True)

        if tax_list:
            args["taxes"] = [{
                "charge_type": tax_list[0]["charge_type"],
                "account_head": tax_list[0]["account_head"],
                "description": tax_list[0]["description"],
                "rate": tax_list[0]["rate"],
                "doctype": "Sales Taxes and Charges"
            }]

        sale = generate_sales_invoice(args)
        handle_payment_and_visit(sale, shop_doc, parsed["payment_type"], parsed["customer"], parsed["branch"], parsed["shop"], parsed["visit_name"])

        update_sales_order_items(cart_items)

    except frappe.ValidationError as e:
        frappe.throw(str(e))
    except UnableToSelectBatchError as e:
        frappe.log_error(f"Unable to select batch for args: {args}", "Batch Selection Error")
        frappe.throw(_(f"Unable to select batch: {str(e)}"))
    except frappe.DoesNotExistError:
        return None

    return sale.name


@frappe.whitelist(allow_guest=False)
def update_invoice_custom_print():
    data = frappe.local.form_dict

    name = data.get("name")
    if not name:
        frappe.throw(_("Missing parameter: name"))

    frappe.db.set_value('Sales Invoice', name, 'custom_print', 1)

    return {"status": "success", "message": f"Invoice {name} updated."}


def on_submit(doc, method):
    status = (doc.custom_payment_status or "").strip().lower()

    if status == "success":
        # build the Payment Entry
        pe: frappe._dict = map_pe(dt=doc.doctype, dn=doc.name)

        # set your custom fields
        pe.mode_of_payment = "MY FATOORAH"
        pe.reference_no    = doc.transaction_id
        pe.paid_to         = "101002024 - MY FATOORAH PAYMENT GATEWAY ACCOUNT - AHW"

        # save & submit
        pe.insert()
        pe.submit()

        frappe.msgprint(_("Payment Entry {0} created").format(pe.name))

    elif status == "":
        # do nothing, allow normal submission
        return

    else:
        # block submission until MyFatoorah callback arrives
        frappe.throw(_("You need to wait for myfootrah response"))





@frappe.whitelist(allow_guest=True)
def create_guest_order():
    try:
        request_data = frappe.request.data
        request_dict = frappe.parse_json(request_data.decode("utf-8"))

        frappe.log_error("Guest Order Creation", f"Received guest order creation request: {request_dict}")

        guest_info = {
            "custom_is_guest_order": 1,
            "custom_address_email": request_dict.get("email"),
            "custom_first_name": request_dict.get("first_name"),
            "custom_last_name": request_dict.get("last_name"),
            "custom_address_line_01": request_dict.get("address_line1"),
            "custom_address_line_02": request_dict.get("address_line2"),
            "custom_address_line_in_arabic": request_dict.get("address_in_arabic"),
            "custom_address_city": request_dict.get("address_city"),
            "custom_address_county": request_dict.get("address_county"),
            "custom_address_state": request_dict.get("address_state"),
            "custom_address_country": request_dict.get("address_country"),
            "custom_address_pin_code": request_dict.get("address_pincode"),
            #"custom_address_email_id": request_dict.get("email"),
            "custom_address_phone": request_dict.get("address_phone"),
            "custom_address_fax": request_dict.get("address_fax"),   
            "custom_longitude": request_dict.get("coustome_longitude"),
            "custom_latitude": request_dict.get("coustome_latitude")
        }

        email = guest_info.get("custom_address_email")
        if not email:
            frappe.log_error("Guest Order Creation", "Guest order creation failed: Email is missing")
            frappe.throw("Email is required for guest order.")

        existing_log = frappe.get_all(
            "App Registration Log",
            filters={"email": email, "status": "Completed"},
            limit_page_length=1
        )
        if existing_log:
            frappe.log_error("Guest Order Creation", f"Guest order creation failed: Account already exists for email {email}")
            frappe.throw(f"Guest order creation failed: Account already exists for email {email}")

        cart = request_dict.get("cart")
        customer_name = email or guest_info["custom_first_name"] + " " + guest_info["custom_last_name"]

        if not cart or not customer_name:
            frappe.log_error("Guest Order Creation", "Guest order creation failed: Cart data or customer name is missing")
            frappe.throw("Guest order creation failed: Cart data or customer name is missing")

        #order_data = {"cart": cart, "customer_name": customer_name}
        #order_data.update(guest_info)

        #from path.to.create_order import create_order  # adapter à ton chemin réel
        response = create_order(**request_dict)
        order_name = response.get("name") 

        if not order_name:
            frappe.log_error("Guest Order Creation", "Guest order creation failed: Order creation did not return an order name")
            frappe.throw("Order creation failed.")

        # Injection dans le Sales Order
        for fieldname, value in guest_info.items():
            if value:
                frappe.db.set_value("Sales Order", order_name, fieldname, value)

        #enqueue(
        #    create_user_and_customer,
        #    queue="default",
        #    timeout=300,
        #    is_async=True,
        #    guest_data=guest_info,
        #    order_name=order_name
        #)
        frappe.log_error("Guest Order Creation", f"Guest Order Creation: Enqueuing account creation for order {order_name} with guest info {guest_info}")
        frappe.enqueue(
            method=create_user_and_customer,
            queue="default",
            timeout=300,
            guest_data=guest_info,
            order_name=order_name,
            #publish_progress=True,
        )

        frappe.msgprint(
            _("Account creation is queued. It may take a few minutes"),
            alert=True,
            indicator="blue",
        )


        return {
            "success": True,
            "order_name": order_name
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Guest Order Creation Failed")
        return {"error": "Order creation failed", "details": str(e)}


@frappe.whitelist(allow_guest=True)
def create_user_and_customer(guest_data=None, order_name=None):
    is_background = bool(order_name)

    if not guest_data:
        request_data = frappe.request.data
        request_dict = frappe.parse_json(request_data.decode('utf-8'))
        guest_data = request_dict.get("data", {})

    try:
        email = "" 
        first_name = "" 
        last_name = ""
        password = frappe.generate_hash(length=12)
        mobile_no = ""
        address_data = ""

        if is_background:
            email = guest_data.get("custom_address_email")
            first_name = guest_data.get("custom_first_name")
            last_name = guest_data.get("custom_last_name")
            mobile_no = guest_data.get("custom_address_phone")
            address_data = {
                "address_title": f"{first_name} {last_name}".strip(),
                "address_type": "Billing",
                "address_line1": guest_data.get("custom_address_line_01"),
                "address_line2": guest_data.get("custom_address_line_02"),
                "address_in_arabic": guest_data.get("custom_address_line_in_arabic"),
                "city": guest_data.get("custom_address_city"),
                "state": guest_data.get("custom_address_state"),
                "pincode": guest_data.get("custom_address_pin_code"),
                "country": guest_data.get("custom_address_country"),
                "phone": mobile_no,
                "email_id": email,
                "custom_longitude": guest_data.get("custom_longitude"),
                "custom_latitude": guest_data.get("custom_latitude"),
            }
        else:
            email = guest_data.get("email")
            first_name = guest_data.get("first_name")
            last_name = guest_data.get("last_name")
            mobile_no = guest_data.get("mobile_no")
            address_data = guest_data.get("address_data", {})

        if not email or not first_name:
            return {"error": "Missing required fields"}

        if is_background:
            log = frappe.get_doc({
                "doctype": "App Registration Log",
                "email": email,
                "mobile": mobile_no,
                "order": order_name,
                "status": "Pending",
                "retry_count": 0
            })
            log.insert(ignore_permissions=True)

        if not frappe.db.exists("User", email):
            user_doc = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "new_password": password,
                "mobile_no": mobile_no,
                "send_welcome_email": 0,
                "roles": [
                    {"role": "Customer"},
                    {"role": "Sales User"},
                    {"role": "APP CUSTOMER"}
                ]
            })
            user_doc.insert(ignore_permissions=True)
            #frappe.db.commit()
            frappe.log_error("User Creation", f"User created successfully for email {email}")
            u_doc = frappe.get_doc("User", email)
            old_user = frappe.session.user
            try:
                frappe.set_user("Administrator")  # ou un user technique System Manager
                keys = generate_keys(u_doc.name)
            finally:
                frappe.set_user(old_user)

            private_key = keys["api_secret"]
            public_key = frappe.db.get_value("User", u_doc.name, "api_key")
        else:
            user_doc = frappe.get_doc("User", email)
            public_key = user_doc.api_key
            private_key = None

        existing_customer = frappe.db.exists("Customer", {"email_id": email})
        if not existing_customer:
            new_customer_code = generate_customer_code()
            customer_doc = frappe.get_doc({
                "doctype": "Customer",
                "name": new_customer_code,
                "custom_customer_code": new_customer_code,
                "customer_name": f"{first_name} {last_name}",
                "email_id": email,
                "customer_group": "App Customer Group",
                "territory": "All Territories",
                "customer_type": "Individual"
            })
            customer_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            frappe.msgprint("Customer created successfully.")

            if address_data:
                create_address_2(address_data, customer_doc.name)

            frappe.db.commit()

            if order_name and frappe.db.exists("Sales Order", order_name):
                frappe.db.set_value("Sales Order", order_name, "customer", new_customer_code)
                new_address = frappe.get_doc("Address", new_customer_code + "_01")
                if new_address:
                    frappe.db.set_value("Sales Order", order_name, "customer_address", new_address.name)
                customer_name = f"{first_name} {last_name}"
                frappe.db.set_value("Sales Order", order_name, "customer_name", customer_name)

        else:
            new_customer_code = frappe.get_value("Customer", {"email_id": email}, "name")

        if is_background:
            user_doc = frappe.get_doc("User", email)
            public_key = user_doc.api_key
            
            log.status = "Completed"
            log.customer_code = new_customer_code
            log.user_email = email
            log.public_key = public_key
            log.private_key = private_key
            log.save(ignore_permissions=True)

        
        

        return {
            "user_email": email,
            "public_key": public_key,
            "private_key": private_key,
            "customer_code": new_customer_code
        }

    except Exception as e:
        frappe.db.rollback()
        if is_background:
            try:
                log.status = "Failed"
                log.error_log = str(e)
                log.retry_count += 1
                log.save(ignore_permissions=True)
            except:
                pass
        frappe.log_error(frappe.get_traceback(), "create_user_and_customer error")
        return {"error": str(e)}


def generate_customer_code():
    last = frappe.get_all(
        "Customer",
        filters={"name": ["like", "AC%"]},
        fields=["name"],
        order_by="name desc",
        limit_page_length=1
    )
    last_code = last[0]["name"] if last else "AC00000000"
    new_number = int(last_code[2:]) + 1
    return f"AC{new_number:08d}"


@frappe.whitelist(allow_guest=True)
def check_user_registration_status(email=None):
    if not email:
        email = frappe.form_dict.get("email")
    if not email:
        return {"error": "Email is required"}

    try:
        log = frappe.get_all(
            "App Registration Log",
            filters={"email": email},
            fields=["status", "customer_code", "user_email", "public_key", "private_key", "order", "creation"],
            order_by="creation desc",
            limit_page_length=1
        )

        if not log:
            return {
                "status": "Not Found",
                "registered": False
            }

        entry = log[0]
        return {
            "status": entry["status"],
            "registered": entry["status"] == "Completed",
            "customer_code": entry["customer_code"] if entry["status"] == "Completed" else None,
            "public_key": entry["public_key"],
            "private_key": entry["private_key"],
            "user_email": entry["user_email"],
            "order": entry["order"]
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in check_user_registration_status")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def check_user_registration_status(email=None, mobile=None):
    email = email or frappe.form_dict.get("email")
    mobile = mobile or frappe.form_dict.get("mobile")

    if not email and not mobile:
        return {"error": "You must provide at least email or mobile number."}

    filters = {}
    if email:
        filters["email"] = email
    if mobile:
        filters["custom_address_phone"] = mobile

    try:
        # Cherche le log correspondant à l'email ou au numéro
        log = frappe.get_all(
            "App Registration Log",
            filters=filters,
            fields=[
                "status", "customer_code", "email",
                "public_key", "private_key", "sales_order", "creation"
            ],
            order_by="creation desc",
            limit_page_length=1
        )

        if not log:
            return {
                "status": "Not Found",
                "registered": False
            }

        entry = log[0]
        return {
            "status": entry["status"],
            "registered": entry["status"] == "Completed",
            "customer_code": entry["customer_code"] if entry["status"] == "Completed" else None,
            "public_key": entry["public_key"],
            "private_key": entry["private_key"],
            "user_email": entry["email"],
            "order": entry["sales_order"]
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "check_user_registration_status error")
        return {"error": str(e)}



@frappe.whitelist()
def payment_customer_address(customer: str):
    """
    Retourne l'adresse pour un client au format attendu par la classe Dart Address:
    {
      "name","address_type","address_line1","address_line2",
      "city","phone","email_id","country","pincode",
      // bonus non requis par la classe:
      "source","display"
    }
    Logique: 1) première facture payée (shipping > billing) ; 2) fallback (primaire > Billing > plus ancienne)
    """
    if not customer:
        frappe.throw("Paramètre 'customer' requis.")
    if not frappe.db.exists("Customer", customer):
        return {}

    # 1) Trouver l'adresse candidate (invoice payée -> fallback)
    row = frappe.db.sql("""
        SELECT t.addr, t.source
        FROM (
          (
            SELECT
              COALESCE(NULLIF(si.shipping_address_name, ''), si.customer_address) AS addr,
              CASE
                WHEN si.shipping_address_name IS NOT NULL AND si.shipping_address_name <> ''
                  THEN CONCAT('invoice:', si.name, ':shipping')
                ELSE CONCAT('invoice:', si.name, ':billing')
              END AS source,
              1 AS priority,
              si.posting_date AS sort_dt
            FROM `tabSales Invoice` si
            WHERE si.customer = %(customer)s
              AND si.docstatus = 1
              AND si.is_return = 0
              AND si.status IN ('Paid','Paid and Closed')
              AND (
                   (si.shipping_address_name IS NOT NULL AND si.shipping_address_name <> '')
                OR (si.customer_address      IS NOT NULL AND si.customer_address      <> '')
              )
              AND EXISTS (
                SELECT 1
                FROM `tabAddress` a
                WHERE a.name = COALESCE(NULLIF(si.shipping_address_name,''), si.customer_address)
                  AND COALESCE(a.disabled, 0) = 0
              )
            ORDER BY si.posting_date ASC, si.name ASC
            LIMIT 1
          )
          UNION ALL
          (
            SELECT a.name AS addr,
                   'fallback:customer_billing_or_primary' AS source,
                   2 AS priority,
                   a.creation AS sort_dt
            FROM `tabAddress` a
            JOIN `tabDynamic Link` dl
              ON dl.parent = a.name AND dl.parenttype = 'Address'
            WHERE dl.link_doctype = 'Customer'
              AND dl.link_name = %(customer)s
              AND COALESCE(a.disabled, 0) = 0
            ORDER BY a.is_primary_address DESC,
                     (a.address_type = 'Billing') DESC,
                     a.creation ASC
            LIMIT 1
          )
        ) AS t
        ORDER BY t.priority ASC, t.sort_dt ASC
        LIMIT 1
    """, {"customer": customer}, as_dict=True)

    if not row:
        return {}

    addr_name = row[0]["addr"]

    # 2) Charger uniquement les champs utiles à ta classe Dart
    fields = [
        "name",
        "address_type",
        "address_line1",
        "address_line2",
        "city",
        "phone",
        "email_id",
        "country",
        "pincode",
    ]
    addr = frappe.db.get_value("Address", addr_name, fields, as_dict=True) or {}

    if not addr:
        return {}

    return addr





@frappe.whitelist()
def test_order(args):
    try:
        sale = frappe.get_doc(args)
        #sale.ignore_pricing_rule = 1
        sale.insert(ignore_permissions=True)
        #sale.submit()
    except frappe.DoesNotExistError:
        frappe.log_error(frappe.get_traceback(), "Create Order Error")
        return None
        
    return sale



