
from django.conf import settings
from django.core import mail
from django.test import TestCase

from license_manager.apps.subscriptions import constants, emails
from license_manager.apps.subscriptions.tests.utils import make_test_email_data


class EmailTests(TestCase):
    def setUp(self):
        super().setUp()
        test_email_data = make_test_email_data()
        self.subscription_plan = test_email_data['subscription_plan']
        self.licenses = test_email_data['licenses']
        self.custom_template_text = test_email_data['custom_template_text']
        self.enterprise_slug = 'mock-enterprise'
        self.email_recipient_list = test_email_data['email_recipient_list']
        self.enterprise_name = 'Mock Enterprise'

    def _assert_bookmark_content_is_present(self, message):
        """
        Helper that asserts bookmark/learner-portal home content is present in the email email content.
        """
        # Verify that the message about bookmarking the learner portal home is in the message body text
        expected_learner_portal_link = settings.ENTERPRISE_LEARNER_PORTAL_BASE_URL + '/' + self.enterprise_slug
        expected_bookmark_message = (
            "So you don't have to search for this link, bookmark your learning portal now to have easy access to your"
            " subscription in the future: "
        )
        self.assertIn(expected_bookmark_message + expected_learner_portal_link, message.body)

        # ...and the HTML
        actual_html = message.alternatives[0][0]
        expected_learner_portal_anchor = '<a href="{}/mock-enterprise"'.format(
            settings.ENTERPRISE_LEARNER_PORTAL_BASE_URL
        )
        expected_bookmark_paragraph = (
            "So you don't have to search for this link, bookmark your learning portal now to have easy access to your"
            " subscription in the future: "
        )
        self.assertIn(expected_learner_portal_anchor, actual_html)
        self.assertIn(expected_bookmark_paragraph, actual_html)

    def test_send_activation_emails(self):
        """
        Tests that activation emails are correctly sent.
        """
        emails.send_activation_emails(
            self.custom_template_text,
            [license for license in self.licenses if license.status == constants.ASSIGNED],
            self.enterprise_slug,
            self.enterprise_name,
        )
        self.assertEqual(
            len(mail.outbox),
            len(self.email_recipient_list)
        )
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, constants.LICENSE_ACTIVATION_EMAIL_SUBJECT)
        self.assertTrue('Activate' in message.body)
        self._assert_bookmark_content_is_present(message)

    def test_send_reminder_email(self):
        """
        Tests that reminder emails are correctly sent.
        """
        lic = self.licenses[0]
        emails.send_activation_emails(
            self.custom_template_text,
            [lic],
            self.enterprise_slug,
            self.enterprise_name,
            is_reminder=True,
        )
        self.assertEqual(len(mail.outbox), 1)
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, constants.LICENSE_REMINDER_EMAIL_SUBJECT)
        self.assertFalse('Activate' in message.body)
        self._assert_bookmark_content_is_present(message)
