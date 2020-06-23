from smtplib import SMTPException

import mock
from django.conf import settings
from django.core import mail
from django.test import TestCase

from license_manager.apps.subscriptions import constants, emails
from license_manager.apps.subscriptions.tests.utils import (
    assert_last_remind_date_correct,
    make_test_email_data,
)


class EmailTests(TestCase):
    def setUp(self):
        super().setUp()
        test_email_data = make_test_email_data()
        self.subscription_plan = test_email_data['subscription_plan']
        self.licenses = test_email_data['licenses']
        self.custom_template_text = test_email_data['custom_template_text']
        self.email_recipient_list = test_email_data['email_recipient_list']

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

    def test_send_reminder_email(self):
        """
        Tests that reminder emails are correctly sent.
        """
        lic = self.licenses[0]
        emails.send_reminder_emails(
            self.custom_template_text,
            [lic.user_email],
            lic.subscription_plan,
        )
        self.assertEqual(len(mail.outbox), 1)
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, constants.LICENSE_REMINDER_EMAIL_SUBJECT)
        # Verify that 'Reminder' does show up for the reminder case
        self.assertTrue('Reminder' in message.body)
        # Verify the 'last_remind_date' of all licenses have been updated
        assert_last_remind_date_correct([lic], True)

    def test_send_reminder_email_failure_no_remind_date_update(self):
        """
        Tests that when sending the remind email fails, last_remind_date is not updated
        """
        send_messages = "%s.%s" % (settings.EMAIL_BACKEND, 'send_messages')
        with mock.patch(send_messages, side_effect=SMTPException):
            lic = self.licenses[1]
            emails.send_reminder_emails(
                self.custom_template_text,
                [lic.user_email],
                lic.subscription_plan,
            )
            # Verify no messages were sent
            self.assertEqual(len(mail.outbox), 0)
            # Verify the 'last_remind_date' was not updated
            assert_last_remind_date_correct([lic], False)
