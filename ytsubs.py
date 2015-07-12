#!/usr/bin/env python3

# Copyright (C) 2014 Alistair Buxton <a.j.buxton@gmail.com>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom
# the Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS
# OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import requests.api
import os
import sys
import jinja2
import datetime
import html
import re

BASE_URL = 'https://www.googleapis.com/youtube/v3'
API_KEY = os.environ.get('YOUTUBE_SERVER_API_KEY')
FEED_TEMPLATE = 'feedtemplate.xml'
UPDATE_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

MAX_DESCRIPTION_LENGTH = 200

DURATION = re.compile(
    'P'   # designates a period
    '(?:(?P<years>\d+)Y)?'   # years
    '(?:(?P<months>\d+)M)?'  # months
    '(?:(?P<weeks>\d+)W)?'   # weeks
    '(?:(?P<days>\d+)D)?'    # days
    '(?:T' # time part must begin with a T
    '(?:(?P<hours>\d+)H)?'   # hourss
    '(?:(?P<minutes>\d+)M)?' # minutes
    '(?:(?P<seconds>\d+)S)?' # seconds
    ')?'   # end of time part
)


def get_channel_for_user(user):
    url = BASE_URL + '/channels?part=id&forUsername=' + user + '&key=' + API_KEY
    response = requests.api.request('GET', url)
    data = response.json()
    return data['items'][0]['id']


def get_playlists(channel):
    playlists = []
    # we have to get the full snippet here, because there is no other way to get the channelId
    # of the channels you're subscribed to. 'id' returns a subscription id, which can only be
    # used to subsequently get the full snippet, so we may as well just get the whole lot up front.
    url = BASE_URL + '/subscriptions?part=snippet&channelId=' + channel + '&maxResults=50&key=' + API_KEY

    next_page = ''
    while True:
        # we are limited to 50 results. if the user subscribed to more than 50 channels
        # we have to make multiple requests here.
        response = requests.api.request('GET', url + next_page)
        data = response.json()
        subs = []
        for i in data['items']:
            if i['kind'] == 'youtube#subscription':
                subs.append(i['snippet']['resourceId']['channelId'])

        # actually getting the channel uploads requires knowing the upload playlist ID, which means
        # another request. luckily we can bulk these 50 at a time.
        purl = BASE_URL + '/channels?part=contentDetails&id=' + '%2C'.join(subs) + '&maxResults=50&key=' + API_KEY
        response = requests.api.request('GET', purl)
        data2 = response.json()
        for i in data2['items']:
            try:
                playlists.append(i['contentDetails']['relatedPlaylists']['uploads'])
            except KeyError:
                pass

        try:  # loop until there are no more pages
            next_page = '&pageToken=' + data['nextPageToken']
        except KeyError:
            break

    return playlists


def get_playlist_items(playlist):
    videos = []

    if playlist:
        # get the last 5 videos uploaded to the playlist
        try:
            url = BASE_URL + '/playlistItems?part=contentDetails&playlistId=' + playlist + '&maxResults=5&key=' + API_KEY
            response = requests.api.request('GET', url)
            data = response.json()
            for i in data['items']:
                if i['kind'] == 'youtube#playlistItem':
                    videos.append(i['contentDetails']['videoId'])
        except Exception as e:
            print(e)
            print(videos)
            sys.exit(-4)

    return videos


def get_real_videos(video_ids):
    purl = BASE_URL + '/videos?part=snippet%2CcontentDetails&id='\
                    + '%2C'.join(video_ids)\
                    + '&maxResults=50&fields=items(contentDetails%2Cid%2Ckind%2Csnippet)'\
                    + '&key=' + API_KEY
    response = requests.api.request('GET', purl)
    data = response.json()

    return data['items']


def chunks(l, n):
    """ Yield successive n-sized chunks from l.
    """
    for i in range(0, len(l), n):
        yield l[i:i + n]


def do_it():
    username = sys.argv[1]

    # get all upload playlists of subbed channels
    playlists = get_playlists(get_channel_for_user(username))

    # get the last 5 items from every playlist
    allitems = []
    for p in playlists:
        allitems.extend(get_playlist_items(p))

    # the playlist items don't contain the correct published date, so now
    # we have to fetch every video in batches of 50.
    allvids = []
    for chunk in chunks(allitems, 50):
        allvids.extend(get_real_videos(chunk))

    # build the atom feed
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(os.getcwd()))

    entries = []

    for v in sorted(allvids, key=lambda k: k['snippet']['publishedAt'], reverse=True)[:50]:
        entries.append({
            'title': html.escape(v['snippet']['title']),
            'link': 'https://youtube.com/watch?v=' + v['id'],
            'author': html.escape(v['snippet']['channelTitle']),
            'pubDate': v['snippet']['publishedAt'],
            'description': parse_description(v['snippet']['description']),
            'thumbnail': v['snippet']['thumbnails']['medium']['url'],
            'duration': parse_duration(v['contentDetails']['duration'])
        })

    with open(sys.argv[2], mode='w') as f:
        f.write(env.get_template(FEED_TEMPLATE).render(
            user=username,
            update_time=datetime.datetime.now().strftime(UPDATE_TIME_FORMAT),
            entries=entries
        ))


def parse_description(description):
    # lol what an awesome pythonic way to to this
    # 1. use description if not longer than max length
    # 2. if longer than max length, cut and add dots
    # 3. escape html stuff
    # 4. replace \n newlines with <br />
    description = description if len(description) <= MAX_DESCRIPTION_LENGTH else description[:MAX_DESCRIPTION_LENGTH] + "…"
    return html.escape(description).replace('\n', '<br />')


def parse_duration(duration):
    duration = DURATION.match(duration).groupdict()
    result = ""
    hours = 0
    if duration['years'] is not None:
        result += duration['years'] + 'y '
    if duration['weeks'] is not None:
        result += duration['weeks'] + 'w '
    if duration['days'] is not None:
        hours += int(duration['days']) * 24
    if duration['hours'] is not None or hours != 0:
        result += repr(int(duration['hours']) + hours) + ':'
    if duration['minutes'] is not None:
        if len(duration['minutes']) == 1:
            result += '0'
        result += duration['minutes'] + ':'
    else:
        result += '00:'
    if duration['seconds'] is not None:
        if len(duration['seconds']) == 1:
            result += '0'
        result += duration['seconds']
    else:
        result += '00'

    return result


if __name__ == '__main__':
    if not len(sys.argv) >= 2:
        print("username and (optionally) destination file must be specified as first and second arguments.")
        sys.exit(-1)
    # check for missing inputs
    if not API_KEY:
        print("YOUTUBE_SERVER_API_KEY variable missing.")
        sys.exit(-1)
    do_it()
