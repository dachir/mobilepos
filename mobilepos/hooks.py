from . import __version__ as app_version

app_name = "mobilepos"
app_title = "Mobilepos"
app_publisher = "Kossivi Amouzou"
app_description = "pos for mobile applications"
app_email = "dodziamouzou@gmail.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/mobilepos/css/mobilepos.css"
# app_include_js = "/assets/mobilepos/js/mobilepos.js"

# include js, css files in header of web template
# web_include_css = "/assets/mobilepos/css/mobilepos.css"
# web_include_js = "/assets/mobilepos/js/mobilepos.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "mobilepos/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
#	"methods": "mobilepos.utils.jinja_methods",
#	"filters": "mobilepos.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "mobilepos.install.before_install"
# after_install = "mobilepos.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "mobilepos.uninstall.before_uninstall"
# after_uninstall = "mobilepos.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "mobilepos.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
    "Sales Invoice": "mobilepos.overrides.sales_invoice.CustomSalesInvoice",
    "Item Price": "mobilepos.overrides.item_price.CustomItemPrice",
    "Stock Ledger Entry": "mobilepos.overrides.stock_ledger_entry.CustomStockLedgerEntry",
    "Personal Data Deletion Request": "mobilepos.overrides.personal_data_deletion_request.CustomPersonalDataDeletionRequest",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
#	"Sales Invoice": {
#        "after_submit": "mobilepos.overrides.sales_invoice.test",
#		"on_update": "mobilepos.overrides.sales_invoice.test",
#		"on_cancel": "method",
#		"on_trash": "method"
#	}
    "Sales Order":{
        "after_save": "mobilepos.mobile_pos.select_shop_on_submit"
    },
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    "cron": {
        "* * * * *": [
            "mobilepos.tasks.cron"
        ],
    },"all": [
        "mobilepos.tasks.all"
    ],
    "daily": [
        "mobilepos.tasks.daily"
    ],
    "hourly": [
        "mobilepos.tasks.hourly",
        #"mobilepos.overrides.personal_data_deletion_request.process_data_deletion_request",
    ],
    "weekly": [
        "mobilepos.tasks.weekly"
    ],
    "monthly": [
        "mobilepos.tasks.monthly"
    ],
}

# Testing
# -------

# before_tests = "mobilepos.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#	"frappe.desk.doctype.event.event.get_events": "mobilepos.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#	"Task": "mobilepos.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["mobilepos.utils.before_request"]
# after_request = ["mobilepos.utils.after_request"]

# Job Events
# ----------
# before_job = ["mobilepos.utils.before_job"]
# after_job = ["mobilepos.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
#	{
#		"doctype": "{doctype_1}",
#		"filter_by": "{filter_by}",
#		"redact_fields": ["{field_1}", "{field_2}"],
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_2}",
#		"filter_by": "{filter_by}",
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_3}",
#		"strict": False,
#	},
#	{
#		"doctype": "{doctype_4}"
#	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#	"mobilepos.auth.validate"
# ]

fixtures = [
    {"dt": "Custom Field", "filters": [["module", "=", "Mobilepos"]]},
    {"dt": "Client Script", "filters": [["enabled", "=", 1],["module", "=", "Mobilepos"]]},
    {"dt": "Server Script", "filters": [["disabled", "=", 0],["module", "=", "Mobilepos"]]},
]