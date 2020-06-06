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
LICENSE_ACTIVATION_EMAIL_SUBJECT = ''  # TODO: Get subject line for each type of email from UX (ENT-2979)
LICENSE_REMINDER_EMAIL_SUBJECT = ''
