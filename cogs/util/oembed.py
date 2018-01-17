# oEmbed data fetching (see http://oembed.com/)

import re
import requests

from . import utils

oEmbed_providers = requests.get('https://oembed.com/providers.json').json()
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
        message = f'No endpoint has been found that matches the url "{url}"'
        super().__init__(message)


class NoOembedData(OembedException):
    def __init__(self, url):
        message = f'Failed to retreive oembed data for the url "{url}"'
        super().__init__(message)


def find_oembed_endpoint(url):
    for provider in oEmbed_providers:
        for endpoint in provider['endpoints']:
            for scheme in endpoint['schemes']:
                if re.match(scheme.replace('//www.', '//'), url.replace('//www.', '//')):
                    return endpoint['url']

    raise EndpointNotFound(url)


async def do_fetch(url):
    try:
        return await utils.fetch_page(url, params={'url': url, 'format': 'json'})
    except:
        try:
            return await utils.fetch_page(url, data={'url': url, 'format': 'json'})
        except:
            return None


async def fetch_oembed_data(url):
    data = None

    try:
        endpoint = find_oembed_endpoint(url)
    except EndpointNotFound:
        for endpoint_url in oEmbed_discovery:
            data = await do_fetch(endpoint_url)
    else:
        data = await do_fetch(endpoint)

    if isinstance(data, dict):
        return data

    raise NoOembedData(url)
