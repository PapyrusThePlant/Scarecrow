# oEmbed data fetching (see http://oembed.com/)

import json
import re

import paths
from . import utils

with open(paths.OEMBED_PROVIDERS, 'r', encoding='utf-8') as fp:
    oEmbed_providers = json.load(fp)

    # Escaoe the special characters in the schemes
    for provider in oEmbed_providers:
        for endpoint in provider['endpoints']:
            endpoint['schemes'] = [s.replace('.', '\.').replace('?', '\?') for s in endpoint.get('schemes', [])]


class OembedException(Exception):
    pass


class EndpointNotFound(OembedException):
    def __init__(self, url):
        message = 'No endpoint has been found that matches the given url. ({})'.format(url)
        super(EndpointNotFound, self).__init__(message)


class NoOembedData(OembedException):
    def __init__(self, url):
        message = 'Failed to retreive oembed data for the given url. ({})'.format(url)
        super(NoOembedData, self).__init__(message)


def find_oembed_endpoint(url):
    discovery = []
    for provider in oEmbed_providers:
        for endpoint in provider['endpoints']:
            if not endpoint['schemes'] and endpoint.get('discovery', False):
                discovery.append(endpoint['url'])
            for scheme in endpoint['schemes']:
                if re.match(scheme, url):
                    return endpoint['url'], None

    if not discovery:
        raise EndpointNotFound(url)

    discovery.reverse()  # Yes, bleh, whatever, get over it
    return None, discovery

async def fetch_oembed_data(url):
    endpoint, discovery = find_oembed_endpoint(url)

    if endpoint is not None:
        return await utils.fetch_page(endpoint, data={'url': url, 'format': 'json'})
    else:
        for endpoint_url in discovery:
            data = await utils.fetch_page(endpoint_url, params={'url': url, 'format': 'json'})
            if isinstance(data, dict):
                return data

        raise NoOembedData(url)
