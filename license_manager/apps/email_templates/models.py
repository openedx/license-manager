from django.db import models
from django.utils.translation import ugettext_lazy as _
from model_utils.models import TimeStampedModel


class EmailTemplate(TimeStampedModel):
    """
    Model for managing email templates customized per enterprise customer.

    .. no_pii: This model has no PII
    """
    ASSIGN, REMIND, REVOKE = ('assign', 'remind', 'revoke')
    EMAIL_TEMPLATE_TYPES = (
        (ASSIGN, _('Assign')),
        (REMIND, _('Remind')),
        (REVOKE, _('Revoke')),
    )

    name = models.CharField(max_length=255)
    enterprise_customer = models.UUIDField(help_text=_('UUID for an EnterpriseCustomer from the Enterprise Service.'))
    email_type = models.CharField(max_length=32, choices=EMAIL_TEMPLATE_TYPES)
    email_subject = models.TextField()
    email_greeting = models.TextField(blank=True, null=True)
    email_closing = models.TextField(blank=True, null=True)
    active = models.BooleanField(
        help_text=_('Make a particular template version active.'),
        default=True,
    )

    class Meta:
        ordering = ('enterprise_customer', '-active',)
        indexes = [
            models.Index(fields=['enterprise_customer', 'email_type'])
        ]

    def __str__(self):
        return '{ec}-{email_type}-{active}'.format(
            ec=self.enterprise_customer,
            email_type=self.email_type,
            active=self.active
        )
