# oEmbed data fetching (see http://oembed.com/)

import json
import re

import paths
from . import utils

with open(paths.OEMBED_PROVIDERS, 'r', encoding='utf-8') as fp:
    oEmbed_providers = json.load(fp)
    oEmbed_discovery = []

    # Escaoe the special characters in the schemes
    for provider in oEmbed_providers:
        for endpoint in provider['endpoints']:
            endpoint['schemes'] = [s.replace('.', '\.').replace('?', '\?') for s in endpoint.get('schemes', [])]
            if not endpoint['schemes'] and endpoint.get('discovery', False):
                oEmbed_discovery.append(endpoint['url'])

    oEmbed_discovery.reverse()  # Yes, bleh, whatever, get over it


class OembedException(Exception):
    pass


class EndpointNotFound(OembedException):
    def __init__(self, url):
        message = 'No endpoint has been found that matches the url "{}"'.format(url)
        super().__init__(message)


class NoOembedData(OembedException):
    def __init__(self, url):
        message = 'Failed to retreive oembed data for the url "{}"'.format(url)
        super().__init__(message)


def find_oembed_endpoint(url):
    for provider in oEmbed_providers:
        for endpoint in provider['endpoints']:
            for scheme in endpoint['schemes']:
                if re.match(scheme.replace('//www.', '//'), url.replace('//www.', '//')):
                    return endpoint['url']

    raise EndpointNotFound(url)


async def fetch_oembed_data(url):
    data = None

    try:
        endpoint = find_oembed_endpoint(url)
    except EndpointNotFound:
        for endpoint_url in oEmbed_discovery:
            try:
                data = await utils.fetch_page(endpoint_url, params={'url': url, 'format': 'json'})
            except:
                try:
                    data = await utils.fetch_page(endpoint_url, data={'url': url, 'format': 'json'})
                except:
                    pass
    else:
        try:
            data = await utils.fetch_page(endpoint, params={'url': url, 'format': 'json'})
        except:
            data = await utils.fetch_page(endpoint, data={'url': url, 'format': 'json'})

    if isinstance(data, dict):
        return data

    raise NoOembedData(url)
