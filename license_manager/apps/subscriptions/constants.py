# License status choices
ACTIVATED = 'activated'
ASSIGNED = 'assigned'
UNASSIGNED = 'unassigned'
DEACTIVATED = 'deactivated'
LICENSE_STATUS_CHOICES = (
    (ACTIVATED, 'Activated'),
    (ASSIGNED, 'Assigned'),
    (UNASSIGNED, 'Unassigned'),
    (DEACTIVATED, 'Deactivated'),
)

# Subject line used for emails
# TODO: Get subject line for each type of email from UX (ENT-2979)
LICENSE_ACTIVATION_EMAIL_SUBJECT = 'edX License Activation'
LICENSE_REMINDER_EMAIL_SUBJECT = 'Reminder: Activate your edX License!'
