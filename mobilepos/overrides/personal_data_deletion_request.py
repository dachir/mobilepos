import frappe
from frappe import _
from frappe.utils import get_datetime, get_fullname, time_diff_in_hours
from frappe.website.doctype.personal_data_deletion_request.personal_data_deletion_request import PersonalDataDeletionRequest

class CustomPersonalDataDeletionRequest(PersonalDataDeletionRequest):
    def disable_user(self):
        user = frappe.get_doc("User", self.email)
        user.enabled = False
        user.save()
        return user


def process_data_deletion_request():
    auto_account_deletion = frappe.db.get_single_value("Website Settings", "auto_account_deletion")
    if auto_account_deletion < 1:
        return

    requests = frappe.get_all(
        "Personal Data Deletion Request", filters={"status": "Pending Approval"}, pluck="name"
    )

    for request in requests:
        doc = frappe.get_doc("Personal Data Deletion Request", request)
        if time_diff_in_hours(get_datetime(), doc.creation) >= auto_account_deletion:
            doc.add_comment(
                "Comment",
                _(
                    "The Mobile User record for this request has been auto-deleted due to inactivity by system admins."
                ),
            )
            doc.validate_data_anonymization()
            user = doc.disable_user()
            doc.anonymize_data()
            doc.notify_user_after_deletion()
            #doc.db_set("status", "Deleted")

            user.delete()