"""
Root API URLs.

All API URLs should be versioned, so urlpatterns should only
contain namespaces for the active versions of the API.
"""
import re

from django.urls import include, path

from license_manager.apps.api.v1 import urls as v1_urls


def optional_trailing_slash(urls):
    for url in urls[0].urlpatterns:
        url.pattern.regex = re.compile(url.pattern.regex.pattern.replace('/$', '/?$'))
    return urls


app_name = 'api'
urlpatterns = [
    path('v1/', optional_trailing_slash(include(v1_urls))),
]
