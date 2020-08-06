from django.test import TestCase

from license_manager.apps.email_templates.tests.factories import (
    EmailTemplateFactory,
)


class SubscriptionsModelTests(TestCase):
    """
    Tests for models in the subscriptions app.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.email_template = EmailTemplateFactory()

    def test_str(self):
        assert str(self.email_template) == '{ec}-{email_type}-{active}'.format(
            ec=self.email_template.enterprise_customer,
            email_type=self.email_template.email_type,
            active=self.email_template.active
        )
