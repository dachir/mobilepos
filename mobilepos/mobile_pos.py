import frappe
from frappe import _
from datetime import datetime
from frappe.core.doctype.user.user import get_timezones
from erpnext.setup.utils import get_exchange_rate

@frappe.whitelist()
def configuration(user):
    data = frappe.db.get_all("Shop", ["*"], filters={"user":user})
    return frappe._dict({
        "business_info": data[0],
        "currency_symbol": data[0].currency_symbol,
        "base_urls": {
            "category_image_url": data[0].category_image_url,
            "brand_image_url": data[0].brand_image_url,
            "product_image_url": data[0].product_image_url,
            "supplier_image_url": data[0].supplier_image_url,
            "shop_image_url": data[0].shop_image_url,
            "admin_image_url": data[0].admin_image_url,
            "customer_image_url": data[0].customer_image_url,
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
def get_documents(doctype=None,list_name=None,shop=None, limit=10, offset=0,name=None):
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
            t1.name,t1.customer_name,t1.mobile_no as mobile,t1.email_id as email,t1.image, 0 as balance, t1.creation as created_at, t1.modified as updated_at,
            t1.territory, t1.warehouse, t1.company, t1.branch, t1.currency, t1.sales_person, t1.default_price_list as selling_price_list, t1.tax_id
            FROM (
                SELECT c.*, s.warehouse, s.company, s.branch, s.currency, s.sales_person 
                FROM tabShop s INNER JOIN tabCustomer c ON s.territory = c.territory 
                WHERE s.name = %(shop)s 
            ) AS t1
            LIMIT %(limit)s OFFSET %(offset)s
            """,{"shop":shop, "limit":int(limit),"offset":int(offset)}, as_dict=1
        )
        if name:
            # Filter data where the name starts with name
            data = [entry for entry in data if name in entry['customer_name'].lower()]

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
                p.tax, b.actual_qty as quantity,p.image,p.order_count,p.supplier_id,p.company_id, p.creation as createdAt, p.modified as updatedAt
            FROM `tabShop` s CROSS JOIN `tabShop Product` p INNER JOIN tabBin b ON p.product_code = b.item_code AND s.warehouse = b.warehouse
            INNER JOIN tabItem i ON i.name = p.product_code
            WHERE i.disabled = 0
            LIMIT %(limit)s OFFSET %(offset)s
            """,{"limit":int(limit),"offset":int(offset)}, as_dict=1
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
        batches = get_batch_qty_2(warehouse=warehouse, item_code = i["product_code"], posting_date = frappe.utils.getdate(), posting_time = datetime.now().strftime("%H:%M:%S"))

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
            invoice_details.append(details)

    args = frappe._dict(
            {
                "doctype": "Sales Invoice",
                "customer": customer,
                "company": company,
                #"set_posting_time": 1,
                #"posting_date": frappe.utils.getdate(),
                #"due_date": frappe.utils.getdate(),
                #"currency": currency,
                "branch": branch,
                "set_warehouse": warehouse,
                #"docstatus": 0,
                "update_stock": 1,
                "sales_reconciliation": sales_person,
                "selling_price_list": selling_price_list,
                #"price_list_currency": currency,
                #"conversion_rate": 1.0,
                "shop":shop,
                "items": invoice_details,
                #"ignore_default_payment_terms_template": 0,
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
            #sale.ignore_pricing_rule = 1
            sale.insert()
            sale.submit()
    except frappe.DoesNotExistError:
            return None
        
    return str(sale.name)


@frappe.whitelist()
def get_name_list(doctype,filters=None, limit=10, offset=0):
    data = []
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
    
