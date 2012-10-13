#!/usr/bin/env python

# Copyright (C) 2012 Lukas Lalinsky
# Distributed under the MIT license, see the LICENSE file for details.

import re
from contextlib import closing
from acoustid.script import run_script
from acoustid.data.stats import update_lookup_stats


def main(script, opts, args):
    db = script.engine.connect()
    redis = script.redis.connect()
    for key, count in redis.hgetall('lookups').iteritems():
        count = int(count)
        date, hour, application_id, type = key.split(':')
        if not count:
            # the only way this could be 0 is if we already processed it and
            # nothing touched it since then, so it's safe to delete
            redis.hdel('lookups', key)
        else:
            update_lookup_stats(db, date, hour, application_id, type, count)
            redis.hincrby('lookups', key, -count)


run_script(main)
