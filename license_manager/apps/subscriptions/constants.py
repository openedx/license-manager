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

# Role-based access control
SUBSCRIPTIONS_ADMIN_ROLE = 'enterprise_subscriptions_admin'

SYSTEM_ENTERPRISE_ADMIN_ROLE = 'enterprise_admin'
SYSTEM_ENTERPRISE_OPERATOR_ROLE = 'enterprise_openedx_operator'
