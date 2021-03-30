"""
Testing utilities for license-manager
"""
import requests


class MockResponse(requests.Response):
    def __init__(self, json_data, status_code, content=None):
        super().__init__()

        self.json_data = json_data
        self.status_code = status_code
        self._content = content

    def json(self):  # pylint: disable=arguments-differ
        return self.json_data
