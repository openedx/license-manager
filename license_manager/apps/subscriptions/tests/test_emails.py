from django.core import mail
from django.test import TestCase

from license_manager.apps.subscriptions import emails
from license_manager.apps.subscriptions.tests.factories import (
    SubscriptionPlanFactory,
)


class EmailTests(TestCase):
    def setUp(self):
        super().setUp()
        self.subscription_plan = SubscriptionPlanFactory()

    def test_activation_emails_sent(self):
        """
        Tests that an activation email is placed in the outbox when sent
        """
        activation_custom_template_text = {
            'greeting': 'Hello',
            'closing': 'Goodbye',
        }
        email_recipient_list = [
            'boatymcboatface@mit.edu',
            'saul.goodman@bettercallsaul.com',
            't.soprano@badabing.net',
        ]
        emails.send_activation_emails(
            activation_custom_template_text,
            email_recipient_list,
            self.subscription_plan.expiration_date
        )
        self.assertEqual(
            len(mail.outbox),
            len(email_recipient_list)
        )
