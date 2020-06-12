from django.core import mail
from django.test import TestCase

from license_manager.apps.subscriptions import constants, emails
from license_manager.apps.subscriptions.tests.factories import (
    SubscriptionPlanFactory,
)


class EmailTests(TestCase):
    def setUp(self):
        super().setUp()
        self.subscription_plan = SubscriptionPlanFactory()
        self.custom_template_text = {
            'greeting': 'Hello',
            'closing': 'Goodbye',
        }
        self.email_recipient_list = [
            'boatymcboatface@mit.edu',
            'saul.goodman@bettercallsaul.com',
            't.soprano@badabing.net',
        ]

    def test_send_activation_emails(self):
        """
        Tests that activation emails are correctly sent.
        """
        emails.send_activation_emails(
            self.custom_template_text,
            self.email_recipient_list,
            self.subscription_plan,
        )
        self.assertEqual(
            len(mail.outbox),
            len(self.email_recipient_list)
        )
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, constants.LICENSE_ACTIVATION_EMAIL_SUBJECT)
        self.assertFalse('Reminder' in message.body)

    def test_send_reminder_emails(self):
        """
        Tests that reminder emails are correctly sent.
        """
        emails.send_reminder_emails(
            self.custom_template_text,
            self.email_recipient_list,
            self.subscription_plan,
        )
        self.assertEqual(
            len(mail.outbox),
            len(self.email_recipient_list)
        )
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, constants.LICENSE_REMINDER_EMAIL_SUBJECT)
        # Verify that 'Reminder' does show up for the reminder case
        self.assertTrue('Reminder' in message.body)
