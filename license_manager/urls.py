"""license_manager URL Configuration
The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.11/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  re_path(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  re_path(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Add an import:  from blog import urls as blog_urls
    2. Add a URL to urlpatterns:  re_path(r'^blog/', include(blog_urls))
"""

import os

from auth_backends.urls import oauth2_urlpatterns
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_yasg.views import get_schema_view
from edx_api_doc_tools import make_api_info
from rest_framework import permissions

from license_manager.apps.api import urls as api_urls
from license_manager.apps.core import views as core_views
from license_manager.apps.subscriptions import urls_admin as subs_url_admin


admin.autodiscover()


api_info = make_api_info(title="License Manager API", version="v1")
schema_view = get_schema_view(
    api_info,
    public=False,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path('', include(oauth2_urlpatterns)),
    path('', include('csrf.urls')),  # Include csrf urls from edx-drf-extensions
    path('admin/', admin.site.urls),
    path('admin-custom/subscriptions/', include(subs_url_admin)),
    path('api/', include(api_urls)),
    path('api-docs/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('auto_auth/', core_views.AutoAuth.as_view(), name='auto_auth'),
    path('health/', core_views.health, name='health'),
]


if settings.DEBUG and os.environ.get('ENABLE_DJANGO_TOOLBAR', False):  # pragma: no cover
    # Disable pylint import error because we don't install django-debug-toolbar
    # for CI build
    import debug_toolbar  # pylint: disable=import-error,useless-suppression
    urlpatterns.append(path('__debug__/', include(debug_toolbar.urls)))
