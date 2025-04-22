#!/usr/bin/env python

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

import datetime
import html
import os
import re
import sys
from itertools import batched
from pathlib import Path

import jinja2
import requests.api

BASE_URL: str = "https://www.googleapis.com/youtube/v3"

FEED_TEMPLATE: str = "feedtemplate.xml"
UPDATE_TIME_FORMAT: str = "%Y-%m-%dT%H:%M:%S%z"

MAX_DESCRIPTION_LENGTH: int = 800
MAX_RESULTS: int = 50

DURATION = re.compile(
    r"P"  # designates a period
    r"(?:(?P<years>\d+)Y)?"  # years
    r"(?:(?P<months>\d+)M)?"  # months
    r"(?:(?P<weeks>\d+)W)?"  # weeks
    r"(?:(?P<days>\d+)D)?"  # days
    r"(?:T"  # time part must begin with a T
    r"(?:(?P<hours>\d+)H)?"  # hourss
    r"(?:(?P<minutes>\d+)M)?"  # minutes
    r"(?:(?P<seconds>\d+)S)?"  # seconds
    r")?"  # end of time part
)


def get_channel_for_user(user):
    url = f"{BASE_URL}/channels?part=id&forUsername={user}&key={API_KEY}"
    response = requests.api.request("GET", url)
    data = response.json()
    return data["items"][0]["id"]


def get_playlists(channel):
    playlists = []
    # we have to get the full snippet here, because there is no other way to get the channelId
    # of the channels you're subscribed to. 'id' returns a subscription id, which can only be
    # used to subsequently get the full snippet, so we may as well just get the whole lot up front.

    # convert to f-string:
    url = (
        f"{BASE_URL}/subscriptions?part=snippet"
        f"&channelId={channel}"
        f"&maxResults={MAX_RESULTS}"
        f"&key={API_KEY}"
    )

    next_page = ""
    while True:
        # we are limited to 50 results. if the user subscribed to more than 50 channels
        # we have to make multiple requests here.
        response = requests.api.request("GET", url + next_page)
        data = response.json()
        subs = []
        for i in data["items"]:
            if i["kind"] == "youtube#subscription":
                subs.append(i["snippet"]["resourceId"]["channelId"])

        # actually getting the channel uploads requires knowing the upload playlist ID, which means
        # another request. luckily we can bulk these 50 at a time.
        purl = (
            f"{BASE_URL}/channels?part=contentDetails"
            f"&id={'%2C'.join(subs)}"
            f"&maxResults={MAX_RESULTS}"
            f"&key={API_KEY}"
        )
        response = requests.api.request("GET", purl)
        data2 = response.json()
        for i in data2["items"]:
            try:
                playlists.append(i["contentDetails"]["relatedPlaylists"]["uploads"])
            except KeyError:
                pass

        try:  # loop until there are no more pages
            next_page = f"&pageToken={data['nextPageToken']}"
        except KeyError:
            break

    return playlists


def get_playlist_items(playlist):
    videos = []

    if playlist:
        # get the last 5 videos uploaded to the playlist
        url = (
            f"{BASE_URL}/playlistItems?part=contentDetails"
            f"&playlistId={playlist}"
            f"&maxResults=5"
            f"&key={API_KEY}"
        )
        response = requests.api.request("GET", url)
        data = response.json()
        if "items" in data:
            for i in data["items"]:
                if i["kind"] == "youtube#playlistItem":
                    videos.append(i["contentDetails"]["videoId"])

    return videos


def get_real_videos(video_ids):
    purl = (
        f"{BASE_URL}/videos?part=snippet%2CcontentDetails"
        f"&id={'%2C'.join(video_ids)}"
        f"&maxResults={MAX_RESULTS}&fields=items(contentDetails%2Cid%2Ckind%2Csnippet)"
        f"&key={API_KEY}"
    )
    response = requests.api.request("GET", purl)
    data = response.json()

    return data["items"]


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
    for chunk in batched(allitems, MAX_RESULTS):
        allvids.extend(get_real_videos(chunk))

    # build the atom feed
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(os.getcwd()))

    entries = []

    for v in sorted(allvids, key=lambda k: k["snippet"]["publishedAt"], reverse=True)[
        :MAX_RESULTS
    ]:
        entries.append(
            {
                "title": html.escape(v["snippet"]["title"]),
                "link": "https://youtube.com/watch?v=" + v["id"],
                "author": html.escape(v["snippet"]["channelTitle"]),
                "pubDate": v["snippet"]["publishedAt"],
                "description": parse_description(v["snippet"]["description"]),
                "thumbnail": v["snippet"]["thumbnails"]["medium"]["url"],
                "duration": parse_duration(v["contentDetails"]["duration"]),
            }
        )

    with open(sys.argv[2], mode="w") as f:
        f.write(
            env.get_template(FEED_TEMPLATE).render(
                user=username,
                update_time=datetime.datetime.now().strftime(UPDATE_TIME_FORMAT),
                entries=entries,
            )
        )


def parse_description(description):
    # lol what an awesome pythonic way to to this
    # 1. use description if not longer than max length
    # 2. if longer than max length, cut and add dots
    # 3. escape html stuff
    # 4. replace \n newlines with <br />
    description = (
        description
        if len(description) <= MAX_DESCRIPTION_LENGTH
        else description[:MAX_DESCRIPTION_LENGTH] + "…"
    )
    return html.escape(description).replace("\n", "<br />")


def parse_duration(duration):
    duration = DURATION.match(duration).groupdict()
    result = ""
    hours = 0
    if duration["years"] is not None:
        result += duration["years"] + "y "
    if duration["weeks"] is not None:
        result += duration["weeks"] + "w "
    if duration["days"] is not None:
        hours += int(duration["days"]) * 24
    if duration["hours"] is not None or hours != 0:
        result += repr(int(duration["hours"]) + hours) + ":"
    if duration["minutes"] is not None:
        if len(duration["minutes"]) == 1:
            result += "0"
        result += duration["minutes"] + ":"
    else:
        result += "00:"
    if duration["seconds"] is not None:
        if len(duration["seconds"]) == 1:
            result += "0"
        result += duration["seconds"]
    else:
        result += "00"

    return result


if __name__ == "__main__":
    if not len(sys.argv) >= 2:
        print(
            "username and (optionally) destination file must be specified as first and second arguments."
        )
        raise SystemError(1)
    # check for missing inputs
    API_KEY: str | None = os.environ.get("YOUTUBE_SERVER_API_KEY")
    if API_KEY is None:
        print("Failed to load API_KEY")
        raise SystemError(1)
    if (api_file := Path(API_KEY)).is_file():
        API_KEY = api_file.read_text().strip()
    do_it()
