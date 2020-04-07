""" Context processor tests. """

from django.test import RequestFactory, TestCase, override_settings

from license_manager.apps.core.context_processors import core


PLATFORM_NAME = 'Test Platform'


class CoreContextProcessorTests(TestCase):
    """ Tests for core.context_processors.core """

    @override_settings(PLATFORM_NAME=PLATFORM_NAME)
    def test_core(self):
        request = RequestFactory().get('/')
        self.assertDictEqual(core(request), {'platform_name': PLATFORM_NAME})
