from django.conf import settings
import responses
from test_plus.test import TestCase

from ..salesforce import get_salesforce_api
from .utils import mock_salesforce_auth


class TestGetSalesforceApi(TestCase):

    def setUp(self):
        self.instance_url = 'https://testinstance.salesforce.com'

    @responses.activate
    def test_get_salesforce_api_production(self):
        """Get API for a production org."""
        mock_salesforce_auth(
            self.instance_url,
            sandbox=settings.SALESFORCE_SANDBOX,
        )
        sfapi = get_salesforce_api(review=False)
        self.assertEqual(len(responses.calls), 1)

    @responses.activate
    def test_get_salesforce_api_review(self):
        """Get API for a sandbox org."""
        mock_salesforce_auth(
            self.instance_url,
            sandbox=settings.SALESFORCE_SANDBOX_REVIEW,
        )
        sfapi = get_salesforce_api(review=True)
        self.assertEqual(len(responses.calls), 1)