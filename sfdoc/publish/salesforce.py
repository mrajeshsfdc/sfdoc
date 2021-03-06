from calendar import timegm
from datetime import datetime
from http import HTTPStatus
from urllib.parse import urljoin
from urllib.parse import urlparse

from django.conf import settings
import jwt
import requests
from simple_salesforce import Salesforce as SimpleSalesforce

from .exceptions import SalesforceError
from .html import HTML
from .models import Article


class Salesforce:
    """Interact with a Salesforce org."""

    def __init__(self):
        self.api = self._get_salesforce_api()

    def _get_salesforce_api(self):
        """Get an instance of the Salesforce REST API."""
        url = settings.SALESFORCE_LOGIN_URL
        if settings.SALESFORCE_SANDBOX:
            url = url.replace('login', 'test')
        payload = {
            'alg': 'RS256',
            'iss': settings.SALESFORCE_CLIENT_ID,
            'sub': settings.SALESFORCE_USERNAME,
            'aud': url,
            'exp': timegm(datetime.utcnow().utctimetuple()),
        }
        encoded_jwt = jwt.encode(
            payload,
            settings.SALESFORCE_JWT_PRIVATE_KEY,
            algorithm='RS256',
        )
        data = {
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': encoded_jwt,
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        auth_url = urljoin(url, 'services/oauth2/token')
        response = requests.post(url=auth_url, data=data, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        sf = SimpleSalesforce(
            instance_url=response_data['instance_url'],
            session_id=response_data['access_token'],
            sandbox=settings.SALESFORCE_SANDBOX,
            version=settings.SALESFORCE_API_VERSION,
            client_id='sfdoc',
        )
        return sf

    def archive(self, ka_id, kav_id):
        """Archive a published article."""
        # delete draft if it exists
        query_str = (
            "SELECT Id FROM {} WHERE KnowledgeArticleId='{}' "
            "AND PublishStatus='draft' AND language='en_US'"
        ).format(
            settings.SALESFORCE_ARTICLE_TYPE,
            ka_id,
        )
        result = self.api.query(query_str)
        if result['totalSize'] > 0:
            self.delete(result['records'][0]['Id'])
        # archive published version
        self.set_publish_status(kav_id, 'archived')

    def create_article(self, html):
        """Create a new article in draft state."""
        kav_api = getattr(self.api, settings.SALESFORCE_ARTICLE_TYPE)
        data = html.create_article_data()
        result = kav_api.create(data=data)
        kav_id = result['id']
        return kav_id

    def create_draft(self, ka_id):
        """Create a draft copy of a published article."""
        url = (
            self.api.base_url +
            'knowledgeManagement/articleVersions/masterVersions'
        )
        data = {'articleId': ka_id}
        result = self.api._call_salesforce('POST', url, json=data)
        if result.status_code != HTTPStatus.CREATED:
            e = SalesforceError((
                'Error creating new draft for KnowlegeArticle (ID={})'
            ).format(ka_id))
            raise(e)
        kav_id = result.json()['id']
        return kav_id

    def delete(self, kav_id):
        """Delete a KnowledgeArticleVersion."""
        url = (
            self.api.base_url +
            'knowledgeManagement/articleVersions/masterVersions/{}'
        ).format(kav_id)
        result = self.api._call_salesforce('DELETE', url)
        if result.status_code != HTTPStatus.NO_CONTENT:
            raise SalesforceError((
                'Error deleting KnowledgeArticleVersion (ID={})'
            ).format(kav_id))

    def get_ka_id(self, kav_id, publish_status):
        """Get KnowledgeArticleId from KnowledgeArticleVersion Id."""
        query_str = (
            "SELECT Id,KnowledgeArticleId FROM {} "
            "WHERE Id='{}' AND PublishStatus='{}' AND language='en_US'"
        ).format(
            settings.SALESFORCE_ARTICLE_TYPE,
            kav_id,
            publish_status,
        )
        result = self.api.query(query_str)
        if result['totalSize'] == 0:
            raise SalesforceError(
                'KnowledgeArticleVersion {} not found'.format(kav_id)
            )
        elif result['totalSize'] == 1:  # can only be 0 or 1
            return result['records'][0]['KnowledgeArticleId']

    def get_articles(self, publish_status):
        """Get all article versions with a given publish status."""
        query_str = (
            "SELECT Id,KnowledgeArticleId,Title,UrlName FROM {} "
            "WHERE PublishStatus='{}' AND language='en_US'"
        ).format(
            settings.SALESFORCE_ARTICLE_TYPE,
            publish_status,
        )
        result = self.api.query(query_str)
        return result['records']

    def get_base_url(self):
        """ Return base URL e.g. https://powerofus.force.com """
        o = urlparse(self.api.base_url)

        domain = '{}.force.com'.format(settings.SALESFORCE_COMMUNITY)

        if settings.SALESFORCE_SANDBOX:
            parts = o.netloc.split('.')
            instance = parts[1]
            sandbox_name = parts[0].split('--')[1]

            domain = '{}-{}.{}.force.com'.format(
                sandbox_name,
                settings.SALESFORCE_COMMUNITY,
                instance
            )

        return '{}://{}'.format(
            o.scheme,
            domain,
        )

    def get_preview_url(self, ka_id, online=False):
        """Article preview URL."""
        preview_url = (
            '{}/knowledge/publishing/'
            'articlePreview.apexp?id={}'
        ).format(
            self.get_base_url(),
            ka_id[:15],  # reduce to 15 char ID
        )
        if online:
            preview_url += '&pubstatus=o'
        return preview_url

    def process_article(self, html, bundle):
        """Create a draft KnowledgeArticleVersion."""

        # update links to draft versions
        html.update_links_draft(self.get_base_url())

        # query for existing article
        result_draft = self.query_articles(html.url_name, 'draft')
        result_online = self.query_articles(html.url_name, 'online')

        if result_draft['totalSize'] == 1:
            # draft exists, update fields
            kav_id = result_draft['records'][0]['Id']
            self.update_draft(kav_id, html)
            if result_online['totalSize'] == 1:
                # published version exists
                status = Article.STATUS_CHANGED
            else:
                # not published
                status = Article.STATUS_NEW
        elif result_online['totalSize'] == 0:
            # new draft, new article
            kav_id = self.create_article(html)
            status = Article.STATUS_NEW
        elif result_online['totalSize'] == 1:
            # new draft of existing article
            record = result_online['records'][0]
            # check for changes in article fields
            if html.same_as_record(record):
                # no update
                return
            # create draft copy of published article
            kav_id = self.create_draft(record['KnowledgeArticleId'])
            self.update_draft(kav_id, html)
            status = Article.STATUS_CHANGED

        self.save_article(kav_id, html, bundle, status)

    def publish_draft(self, kav_id):
        """Publish a draft KnowledgeArticleVersion."""
        kav_api = getattr(self.api, settings.SALESFORCE_ARTICLE_TYPE)
        kav = kav_api.get(kav_id)
        body = kav[settings.SALESFORCE_ARTICLE_BODY_FIELD]
        body = HTML.update_links_production(body)

        data = {settings.SALESFORCE_ARTICLE_BODY_FIELD: body}

        if settings.SALESFORCE_ARTICLE_TEXT_INDEX_FIELD is not False:
            data[settings.SALESFORCE_ARTICLE_TEXT_INDEX_FIELD] = body

        kav_api.update(kav_id, data)
        self.set_publish_status(kav_id, 'online')

    def query_articles(self, url_name, publish_status):
        """Query KnowledgeArticleVersion objects."""
        query_str = (
            "SELECT Id,KnowledgeArticleId,Title,Summary,"
            "IsVisibleInCsp,IsVisibleInPkb,IsVisibleInPrm,{},{},{} FROM {} "
            "WHERE UrlName='{}' AND PublishStatus='{}' AND language='en_US'"
        ).format(
            settings.SALESFORCE_ARTICLE_BODY_FIELD,
            settings.SALESFORCE_ARTICLE_AUTHOR_FIELD,
            settings.SALESFORCE_ARTICLE_AUTHOR_OVERRIDE_FIELD,
            settings.SALESFORCE_ARTICLE_TYPE,
            url_name,
            publish_status,
        )
        result = self.api.query(query_str)
        return result

    def save_article(self, kav_id, html, bundle, status):
        """Create an Article object from parsed HTML."""
        ka_id = self.get_ka_id(kav_id, 'draft')
        Article.objects.create(
            bundle=bundle,
            ka_id=ka_id,
            kav_id=kav_id,
            preview_url=self.get_preview_url(ka_id),
            status=status,
            title=html.title,
            url_name=html.url_name,
        )

    def set_publish_status(self, kav_id, status):
        url = (
            self.api.base_url +
            'knowledgeManagement/articleVersions/masterVersions/{}'
        ).format(kav_id)
        data = {'publishStatus': status}
        result = self.api._call_salesforce('PATCH', url, json=data)
        if result.status_code != HTTPStatus.NO_CONTENT:
            raise SalesforceError((
                'Error setting status={} for KnowledgeArticleVersion (ID={})'
            ).format(status, kav_id))

    def update_draft(self, kav_id, html):
        """Update the fields of an existing draft."""
        kav_api = getattr(self.api, settings.SALESFORCE_ARTICLE_TYPE)
        data = html.create_article_data()
        result = kav_api.update(kav_id, data)
        if result != HTTPStatus.NO_CONTENT:
            raise SalesforceError((
                'Error updating draft KnowledgeArticleVersion (ID={})'
            ).format(kav_id))
        return result
