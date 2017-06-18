import aiohttp
import random

import discord
import discord.ext.commands as commands
from lxml import etree
from urllib.parse import urlparse, parse_qs

import paths
from .util import agarify, utils


def setup(bot):
    bot.add_cog(Misc(bot))


class Misc:
    """No comment."""
    def __init__(self, bot):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36'
        }
        self.google_session = aiohttp.ClientSession(headers=headers, loop=bot.loop)

    def __unload(self):
        self.google_session.close()

    @commands.group(invoke_without_command=True)
    async def agarify(self, ctx, *, content):
        """Agarifies a string."""
        await ctx.send(agarify.agarify(content))

    @agarify.command()
    async def user(self, ctx, *, user: discord.Member):
        """Agarifies a user's name."""
        await ctx.send(agarify.agarify(user.display_name, True))

    @commands.command(aliases=['meow'])
    async def cat(self, ctx):
        """Meow !"""
        providers = [
            ('http://random.cat/meow', lambda d: d['file']),
            ('http://edgecats.net/random', lambda d: d),
            ('http://thecatapi.com/api/images/get?format=src', lambda d: d)
        ]
        url, loader = random.choice(providers)

        data = await utils.fetch_page(url, timeout=5)
        if data is None:
            content = f'Timed out on {url} .'
        else:
            content = loader(data)

        await ctx.send(content)

    def parse_google_card(self, node):
        if node is None:
            return None

        e = discord.Embed(colour=0x738bd7)

        # check if it's a calculator card:
        calculator = node.find(".//div[@id='cwmcwd']")
        if calculator is not None:
            try:
                formula = calculator.find(".//span[@id='cwles']").text.strip()
                result = calculator.find(".//span[@id='cwos']").text.strip()
            except:
                return None
            else:
                e.title = 'Calculator'
                e.description = f'{formula} {result}'
            return e

        # check for unit conversion card
        # The 'main' div contains 2 div for the source and the target of the conversion.
        # Each contains an <input> and a <select> where we can find the value and the label of the used unit.
        unit = node.find(".//div[@class='vk_c _cy obcontainer card-section']")
        if unit is not None:
            try:
                source = unit.find(".//div[@id='_Aif']")
                source_value = source.find("./input").attrib['value']
                source_unit = source.find("./select/option[@selected='1']").text
                target = unit.find(".//div[@id='_Cif']")
                target_value = target.find("./input").attrib['value']
                target_unit = target.find(".//select/option[@selected='1']").text
            except:
                return None
            else:
                e.title = 'Unit Conversion'
                e.description = f'{source_value} {source_unit} = {target_value} {target_unit}'
                return e

        # check for currency conversion card
        # The 'main' div contains 2 div for the source and the target of the conversion.
        # The source div has a span with the value in its content, and the unit in the tail
        # The target div has 2 spans, respectively containing the value and the unit
        currency = node.find(".//div[@class='currency g vk_c obcontainer']")
        if currency is not None:
            try:
                source = ''.join(currency.find(".//div[@class='vk_sh vk_gy cursrc']").itertext()).strip()
                target = ''.join(currency.find(".//div[@class='vk_ans vk_bk curtgt']").itertext()).strip()
            except:
                return None
            else:
                e.title = 'Currency Conversion'
                e.description = f'{source} {target}'
                return e

        # Check for translation card
        translation = node.find(".//div[@id='tw-ob']")
        if translation is not None:
            try:
                source_language = translation.find(".//select[@id='tw-sl']").attrib['data-dsln']
                target_language = translation.find(".//select[@id='tw-tl']/option[@selected='1']").text
                translation = translation.find(".//pre[@id='tw-target-text']/span").text
            except:
                return None
            else:
                e.title = f'Translation from {source_language} to {target_language}'
                e.description = translation
                return e

        # check for definition card
        definition = node.find(".//div[@id='uid_0']//div[@class='lr_dct_ent vmod']")
        if definition is not None:
            try:
                e.title = definition.find("./div[@class='vk_ans']/span").text
                definition_info = definition.findall("./div[@class='vmod']/div")
                e.description = definition_info[0].getchildren()[0].getchildren()[0].text  # yikes v2
                for category in definition_info[1:]:
                    lexical_category = category.find("./div[@class='lr_dct_sf_h']/i/span").text
                    definitions = category.findall("./ol/li/div[@class='vmod']//div[@class='_Jig']/div/span")
                    body = []
                    for index, definition in enumerate(definitions, 1):
                        body.append(f'{index}. {definition.text}')
                    e.add_field(name=lexical_category, value='\n'.join(body), inline=False)
            except:
                return None
            else:
                return e

        # check for "time in" card
        time_in = node.find(".//div[@class='vk_c vk_gy vk_sh card-section _MZc']")
        if time_in is not None:
            try:
                time_place = time_in.find("./span").text
                the_time = time_in.find("./div[@class='vk_bk vk_ans']").text
                the_date = ''.join(time_in.find("./div[@class='vk_gy vk_sh']").itertext()).strip()
            except:
                return None
            else:
                e.title = time_place
                e.description = f'{the_time}\n{the_date}'
                return e

        # check for weather card
        weather = node.find(".//div[@id='wob_wc']")
        if weather is not None:
            try:
                location = weather.find("./div[@id='wob_loc']").text
                summary = weather.find(".//span[@id='wob_dc']").text
                image = 'https:' + weather.find(".//img[@id='wob_tci']").attrib['src']
                temp_degrees = weather.find(".//span[@id='wob_tm']").text
                temp_farenheit = weather.find(".//span[@id='wob_ttm']").text
                precipitations = weather.find(".//span[@id='wob_pp']").text
                humidity = weather.find(".//span[@id='wob_hm']").text
                wind_kmh = weather.find(".//span[@id='wob_ws']").text
                wind_mph = weather.find(".//span[@id='wob_tws']").text
            except:
                return None
            else:
                e.title = f'Weather in {location}'
                e.description = summary
                e.set_thumbnail(url=image)
                e.add_field(name='Temperature', value=f'{temp_degrees}°C - {temp_farenheit}°F')
                e.add_field(name='Precipitations', value=precipitations)
                e.add_field(name='Humidity', value=humidity)
                e.add_field(name='Wind speed', value=f'{wind_kmh} - {wind_mph}')
                return e

        # Check for quick search, release date or timeline
        # Those 3 cards follow the same base structure
        # Define which one it is here and parse it afterward
        quick_search = node.find(".//div[@class='xpdopen']/div[@class='_OKe']")
        release = None
        timeline = None
        if quick_search is not None:
            # Try to match things specific to the timeline or release date card
            timeline = quick_search.find("./div/div[@class='mod']/div[@class='_l6j']")
            release_body = quick_search.find(".//div[@class='kp-header']/div[@class='_axe _T9h kp-rgc']")

            # Check the results
            if timeline is not None:
                quick_search = None
            elif release_body is not None:
                release = quick_search
                quick_search = None

        # Parse release date cards
        # The 'main' div has 2 sections, one for the 'title', one for the 'body'.
        # The 'title' is a serie of 3 spans, 1st and 3rd with another nexted span containing the info, the 2nd
        # just contains a forward slash.
        # The 'body' is separated in 2 divs, one with the date and extra info, the other with 15 more nested
        # divs finally containing a <a> from which we can extract the thumbnail url.
        if release is not None:
            # Extract the release card title
            try:
                title = ' '.join(release.find(".//div[@class='_tN _IWg mod']/div[@class='_f2g']").itertext()).strip()
            except:
                e.title = 'Date info'
            else:
                e.title = title

            # Extract the date info
            try:
                description = '\n'.join(release_body.find("./div[@class='_cFb']//div[@class='_uX kno-fb-ctx']").itertext()).strip()
            except:
                return None
            else:
                e.description = description

            # Extract the thumbnail
            thumbnail = release_body.find("./div[@class='_bFb']//a[@class='bia uh_rl']")
            if thumbnail is not None:
                e.set_thumbnail(url=parse_qs(urlparse(thumbnail.attrib['href']).query)['imgurl'][0])

            return e

        # Parse timeline cards
        if timeline is not None:
            try:
                title = timeline.find("./div[@class='_NZg']").text
                table = timeline.find("./div/table/tbody")
                body = []
                for row in table:
                    body.append(' - '.join(row.itertext()).strip())
            except:
                return None
            else:
                e.title = title
                lf = '\n'
                e.description = f'*{body[0]}*\n{lf.join(body[1:])}'
                return e

        # Parse quick search cards
        if quick_search is not None:
            try:
                title_node = quick_search.find("./div/div[@class='g']//a")
                if title_node is not None:
                    # Let's call this the rich quick search card
                    title = title_node.text
                    url = title_node.attrib['href']
                    summary = ''.join(quick_search.find("./div/div[@class='mod']/div[@class='_oDd']/span[@class='_Tgc']").itertext()).strip()
                    image = quick_search.find("./div/div[@class='_tN _VCh _WCh _IWg mod']//a[@class='bia uh_rl']")
                    thumbnail = parse_qs(urlparse(image.attrib['href']).query)['imgurl'][0] if image is not None else None
                else:
                    # And let's call this the poor quick search card
                    title_node = quick_search.find("./div/div[@class='_tN _IWg mod']/div[@class='_f2g']")
                    title = ' '.join(title_node.itertext()).strip()
                    body_node = quick_search.find("./div/div[@class='kp-header']//a")
                    summary = body_node.text
                    url = f'https://www.google.com{body_node.attrib["href"]}'
                    thumbnail = None
            except:
                pass
            else:
                e.title = title
                e.url = url
                e.description = summary
                if thumbnail:
                    e.set_thumbnail(url=thumbnail)
                return e

        # TODO : look for the side cards for people, places, events, they're under a higher node than our current card root
        # Examples queries: `New York`, `Einstein`, `olympic`
        # Watch for queries like `flag of france` having a quick search card along with the side card

        # nothing matched
        return None

    @commands.command(aliases=['g'])
    async def google(self, ctx, *, query):
        """Search for something on google."""
        params = {
            'hl': 'en',
            'q': query,
            'safe': 'on'
        }
        async with self.google_session.get('https://www.google.com/search', params=params) as resp:
            if resp.status != 200:
                await ctx.send(utils.HTTPError(resp, 'Error while querying google.'))
                return
            data = await resp.text()

        root = etree.fromstring(data, etree.HTMLParser())
        # with open('google.html', 'w', encoding='utf-8') as f:
        #     f.write(etree.tostring(root, pretty_print=True).decode('utf-8'))

        # Extract all the nodes with relevant search results
        search_nodes = root.findall(".//div[@class='g']")
        youtube_card = root.find(".//div[@class='g mnr-c g-blk']")  # Special case while we can't embed videos
        if youtube_card is not None:
            search_nodes.insert(0, youtube_card)

        # Retrieve the result links
        search_results = []
        for node in search_nodes:
            try:
                # Skip the image results
                if node.attrib['id'] == 'imagebox_bigimages':
                    continue
            except KeyError:
                pass

            url_node = node.find(".//h3/a")
            if url_node is None:
                # Skip unusual results
                continue

            url = url_node.attrib['href']
            title = url_node.text
            try:
                description = ''.join(node.find(".//span[@class='st']").itertext()).strip()
            except:
                description = ''

            search_results.append((title, url, description))
        top_n = min(3, len(search_results))

        # Try to parse google cards
        embed = self.parse_google_card(root.find(".//div[@id='res']"))
        if not embed:
            # No card found
            if top_n == 0:
                raise commands.BadArgument('No result found.')

            # Build the response from the search results
            title, url, description = search_results[0]
            additional_results = '\n'.join(f'<{r[1]}>' for r in search_results[1:min(top_n + 1, len(search_results))])

            # Text response
            response = f'**{title}**\n{url}\n{description}\n\n**Additional Results**\n{additional_results}'
            await ctx.send(response)

            # Embed response (not worth using when the search return a link to a video)
            # embed = discord.Embed(colour=0x738bd7, title=title, url=url, description=description)
            # embed.add_field(name='Additional Results', value=additional_results, inline=False)
        else:
            # Add the search results to the embed with the card info
            if top_n > 0:
                additional_results = '\n'.join(r[1] for r in search_results[:top_n])
                embed.add_field(name='Additional Results', value=additional_results, inline=False)
            # Display the result
            await ctx.send(embed=embed)

    @commands.command()
    async def insult(self, ctx):
        """Poke the bear."""
        await ctx.send(utils.random_line(paths.INSULTS))

    @commands.command()
    async def weebnames(self, ctx, wanted_gender=None):
        """Looking for a name for your new waifu?

        A prefered gender can be specified between f(emale), m(ale), x(mixed).
        """
        content = ''
        for i in range(1, 10):
            # Get a random name satisfying the wanted gender and kick the '\n' out
            def predicate(line):
                return line[0] == wanted_gender
            line = utils.random_line(paths.WEEBNAMES, predicate if wanted_gender else None)
            gender, name, remark = line[:-1].split('|')
            content += f'[{gender}] {name} {f"({remark})" if remark else ""}\n'

        await ctx.send(utils.format_block(content))
