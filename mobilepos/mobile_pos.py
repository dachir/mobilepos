import frappe
from frappe import _
from frappe.utils import flt
from datetime import datetime
from frappe.core.doctype.user.user import get_timezones
from erpnext.setup.utils import get_exchange_rate
from erpnext.selling.doctype.customer.customer import get_credit_limit, get_customer_outstanding

import json

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
        WHERE 50 BETWEEN a.min_qty AND a.max_qty
        """,{"warehouse": warehouse, "item": item, "customer_group":customer_group, "qty": qty}, as_dict = 1
    )

    if data:
        return data
    else:
        return []

@frappe.whitelist()
def configuration(user):
    data = frappe.get_doc("Shop", {"user":user})
    return frappe._dict({
        "business_info": data,
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
            SELECT YEAR(posting_date) as 'year', MONTH(posting_date) as 'month', SUM(net_total) as net_total
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
            SELECT YEAR(posting_date) as 'year', MONTH(posting_date) as 'month', SUM(net_total) as net_total
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
        SELECT (SELECT SUM(net_total) as net_total
        FROM `tabSales Invoice`
        WHERE shop=%s AND YEAR(posting_date) = YEAR(CURDATE()) {condition}) as net_total,
        (SELECT SUM(paid_amount) as paid_amount
        FROM `tabPayment Entry`
        WHERE shop=%s AND YEAR(posting_date) = YEAR(CURDATE()) {condition}) as paid_amount

        """.format(condition=condition),(shop,shop),as_dict=1
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
def get_documents(doctype=None,list_name=None,shop=None, limit=10, offset=0,name=None, company=None):
    if not doctype in ["Shop Invoice"]:
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
        data = frappe.db.sql(
            """
            SELECT (SELECT COUNT(*) + 1 FROM tabCustomer t2 WHERE t2.name <= t1.name) AS id,
            t1.name,CASE WHEN t1.name <> t1.customer_name THEN CONCAT(t1.name,' ',t1.customer_name) ELSE t1.customer_name END AS customer_name,
            t1.mobile_no as mobile,t1.email_id as email,t1.image, 0 as balance, t1.creation as created_at, t1.modified as updated_at,
            t1.territory, t1.warehouse, t1.company, t1.branch, t1.currency, t1.sales_person, t1.default_price_list as selling_price_list, t1.tax_id
            FROM (
                SELECT c.*, s.warehouse, s.company, s.branch, s.currency, s.sales_person 
                FROM tabShop s INNER JOIN `tabShop Territory` t ON t.parent = s.name INNER JOIN tabCustomer c ON t.territory = c.territory 
                WHERE s.name = %(shop)s and CONCAT(c.name,' ',lower(c.customer_name)) LIKE CONCAT('%%',lower(%(name)s),'%%')
            ) AS t1
            LIMIT %(limit)s OFFSET %(offset)s
            """,{"shop":shop, "name":name, "limit":int(limit),"offset":int(offset)}, as_dict=1
        )

        for i in data:
            outstanding_amt = get_customer_outstanding(
                i.name, company, ignore_outstanding_sales_order=i.bypass_credit_limit_check
            )
            credit_limit = get_credit_limit(i.name, company)

            bal = flt(credit_limit) - flt(outstanding_amt)
            i.update({
                "balance": bal
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
            SELECT i.name as invoice_number, i.posting_date as date, i.net_total, i.paid_amount, i.outstanding_amount, i.customer
            FROM `tabSales Invoice` i INNER JOIN `tabShop` s ON i.sales_reconciliation = s.sales_person
            WHERE i.outstanding_amount > 0 AND s.name= %(shop)s AND i.customer = %(name)s AND i.docstatus = 1
            """,{"shop":shop,"name":name}, as_dict=1
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
        SELECT t.posting_date, SUM(t.net_total) AS net_total, SUM(t.paid_amount) AS paid_amount
        FROM(
            SELECT posting_date, SUM(net_total) as net_total, 0 as paid_amount
            FROM `tabSales Invoice`
            WHERE shop=%(shop)s AND docstatus <> 2 {condition} {si_condition}
            GROUP BY posting_date
            UNION
            SELECT DISTINCT posting_date, 0 as net_total, SUM(paid_amount) as paid_amount
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


@frappe.whitelist()
def create_invoice():
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

    invoice_details = []
    temp_batches = []
    for i in cart_data:
        if i["quantity"] == 0:
            continue

        
        
        from erpplus.utils import get_batch_qty_2
        max_qty = i["quantity"]

        customer_group = frappe.db.get_value("Customer",customer, "customer_group")
        promo_data = get_promotion(warehouse, i["product_code"], customer_group, max_qty)
        #batches = get_batch_qty_2(warehouse=warehouse, item_code = i["product_code"], posting_date = frappe.utils.getdate(), posting_time = datetime.now().strftime("%H:%M:%S"))

        batches = frappe.db.sql(
            """
            SELECT sle.batch_no, SUM(sle.actual_qty) AS qty
            FROM `tabStock Ledger Entry` sle
            WHERE (sle.is_cancelled = 0) AND (sle.item_code = %(item_code)s) AND (sle.warehouse = %(warehouse)s) AND (sle.actual_qty <> 0)
            GROUP BY sle.batch_no
            HAVING SUM(sle.actual_qty) > 0
            """, {"warehouse": warehouse, "item_code": i["product_code"]}, as_dict = 1
        )

        for b in batches:
            t_batch = frappe._dict({"batch_no" : b.batch_no,"item_code":i["product_code"], "qty": b.qty})
            temp_batches.append(t_batch)

        item_code = i["product_code"]
        filtered_batches = [d for d in temp_batches if d["item_code"] == item_code]

        for b in filtered_batches:
            if not b.qty:
                continue
            if b.qty <= 0:
                continue

            while b.qty > 0 and max_qty > 0:
                if b.qty >= max_qty:
                    details = frappe._dict({
                        "doctype": "Sales Invoice Item",
                        "item_code": i["product_code"],
                        "qty": max_qty,
                        "batch_no": b.batch_no,
                        "branch": branch,
                    })
                    if len(promo_data) > 0:
                        if promo_data[0].price_or_product_discount == "Price":
                            details.update({"rate": promo_data[0].rate})
                    invoice_details.append(details)
                    b.qty -= max_qty
                    max_qty = 0
                    temp_batches[temp_batches.index(b)] = b
                    break
                else:
                    details = frappe._dict({
                        "doctype": "Sales Invoice Item",
                        "item_code": i["product_code"],
                        "qty": b.qty,
                        "batch_no": b.batch_no,
                        "branch": branch,
                    })
                    if len(promo_data) > 0:
                        if promo_data[0].price_or_product_discount == "Price":
                            details.update({"rate": promo_data[0].rate})
                    invoice_details.append(details)
                    max_qty = max_qty - b.qty
                    b.qty = 0
                    temp_batches[temp_batches.index(b)] = b

        if max_qty > 0:
            details = frappe._dict({
                "doctype": "Sales Invoice Item",
                "item_code": i["product_code"],
                "qty": max_qty,
                "branch": branch,
            })
            if len(promo_data) > 0:
                if promo_data[0].price_or_product_discount == "Price":
                    details.update({"rate": promo_data[0].rate})
            invoice_details.append(details)

        if len(promo_data) > 0:
            for p in promo_data:
                if p["price_or_product_discount"] == "Product":
                    details = frappe._dict({
                        "doctype": "Sales Invoice Item",
                        "item_code": p["free_item"],
                        "qty": p["total_free_qty"],
                        "rate": 0,
                        "price_list_rate": 0,
                        "branch": branch,
                    })
                    invoice_details.append(details)

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
            #add submit
            sale.submit()
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

    received_amount = request_dict.get('paid_amount')
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
        payment.insert()
        payment.submit()
    except frappe.DoesNotExistError:
        return None
    except Exception as e:
    # Handle other exceptions by logging or custom logic
        frappe.throw(f"An error occurred: {str(e)}")
        
    return str(payment.name)


