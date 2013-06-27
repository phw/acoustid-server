# Copyright (C) 2011 Lukas Lalinsky
# Distributed under the MIT license, see the LICENSE file for details.

import logging
import re
from sqlalchemy import sql
from acoustid import tables as schema

logger = logging.getLogger(__name__)


def _load_artists(conn, artist_credit_ids):
    if not artist_credit_ids:
        return {}
    src = schema.mb_artist_credit_name
    src = src.join(schema.mb_artist)
    condition = schema.mb_artist_credit_name.c.artist_credit.in_(artist_credit_ids)
    columns = [
        schema.mb_artist_credit_name.c.name,
        schema.mb_artist_credit_name.c.artist_credit,
        schema.mb_artist_credit_name.c.join_phrase,
        schema.mb_artist.c.gid
    ]
    query = sql.select(columns, condition, from_obj=src).\
        order_by(schema.mb_artist_credit_name.c.artist_credit,
                 schema.mb_artist_credit_name.c.position)
    result = {}
    for row in conn.execute(query):
        ac_data = {
            'id': row['gid'],
            'name': row['name'],
        }
        if row['join_phrase']:
            ac_data['joinphrase'] = row['join_phrase']
        result.setdefault(row['artist_credit'], []).append(ac_data)
    return result


def _load_release_meta(conn, release_ids):
    if not release_ids:
        return {}
    src = schema.mb_medium
    condition = schema.mb_medium.c.release.in_(release_ids)
    columns = [
        schema.mb_medium.c.release,
        sql.func.count(schema.mb_medium.c.id).label('release_medium_count'),
        sql.func.sum(schema.mb_medium.c.track_count).label('release_track_count'),
    ]
    query = sql.select(columns, condition, from_obj=src,
                group_by=schema.mb_medium.c.release)
    result = {}
    for row in conn.execute(query):
        result[row['release']] = {
            'release_medium_count': row['release_medium_count'],
            'release_track_count': row['release_track_count']
        }
    return result


def _load_release_events(conn, release_ids):
    if not release_ids:
        return {}
    src = schema.mb_release_country
    src = src.outerjoin(schema.mb_iso_3166_1, schema.mb_iso_3166_1.c.area == schema.mb_release_country.c.country)
    condition = schema.mb_release_country.c.release.in_(release_ids)
    columns = [
        schema.mb_release_country.c.release,
        schema.mb_iso_3166_1.c.code.label('release_country'),
        schema.mb_release_country.c.date_year.label('release_date_year'),
        schema.mb_release_country.c.date_month.label('release_date_month'),
        schema.mb_release_country.c.date_day.label('release_date_day'),
    ]
    query = sql.select(columns, condition, from_obj=src)
    result = {}
    for row in conn.execute(query):
        result.setdefault(row['release'], []).append({
            'release_country': row['release_country'],
            'release_date_year': row['release_date_year'],
            'release_date_month': row['release_date_month'],
            'release_date_day': row['release_date_day'],
        })
    return result


def _load_release_groups(conn, release_group_ids):
    if not release_group_ids:
        return {}
    src = schema.mb_release_group
    src = src.outerjoin(schema.mb_release_group_primary_type, schema.mb_release_group.c.type == schema.mb_release_group_primary_type.c.id)
    condition = schema.mb_release_group.c.id.in_(release_group_ids)
    columns = [
        schema.mb_release_group.c.id.label('release_group_rid'),
        schema.mb_release_group.c.gid.label('release_group_id'),
        schema.mb_release_group.c.name.label('release_group_title'),
        schema.mb_release_group.c.artist_credit.label('release_group_artist_credit'),
        schema.mb_release_group_primary_type.c.name.label('release_group_primary_type'),
    ]
    query = sql.select(columns, condition, from_obj=src)
    result = {}
    for row in conn.execute(query):
        result[row['release_group_rid']] = {
            'release_group_id': row['release_group_id'],
            'release_group_title': row['release_group_title'],
            'release_group_artist_credit': row['release_group_artist_credit'],
            'release_group_primary_type': row['release_group_primary_type'],
        }
    return result


def lookup_metadata(conn, recording_ids, load_releases=False, load_release_groups=False, load_artists=False):
    if not recording_ids:
        return []
    src = schema.mb_recording
    columns = [
        schema.mb_recording.c.gid.label('recording_id'),
        schema.mb_recording.c.artist_credit.label('recording_artist_credit'),
        schema.mb_recording.c.name.label('recording_title'),
        (schema.mb_recording.c.length / 1000).label('recording_duration'),
    ]
    if load_releases:
        src = src.join(schema.mb_track, schema.mb_recording.c.id == schema.mb_track.c.recording)
        src = src.join(schema.mb_medium, schema.mb_track.c.medium == schema.mb_medium.c.id)
        src = src.join(schema.mb_release, schema.mb_medium.c.release == schema.mb_release.c.id)
        src = src.outerjoin(schema.mb_medium_format, schema.mb_medium.c.format == schema.mb_medium_format.c.id)
        columns.extend([
            schema.mb_track.c.gid.label('track_id'),
            schema.mb_track.c.position.label('track_position'),
            schema.mb_track.c.name.label('track_title'),
            schema.mb_track.c.artist_credit.label('track_artist_credit'),
            (schema.mb_track.c.length / 1000).label('track_duration'),
            schema.mb_medium.c.position.label('medium_position'),
            schema.mb_medium.c.track_count.label('medium_track_count'),
            schema.mb_medium_format.c.name.label('medium_format'),
            schema.mb_release.c.id.label('release_rid'),
            schema.mb_release.c.gid.label('release_id'),
            schema.mb_release.c.name.label('release_title'),
            schema.mb_release.c.artist_credit.label('release_artist_credit'),
            schema.mb_release.c.release_group.label('release_group_rid'),
        ])
    condition = schema.mb_recording.c.gid.in_(recording_ids)
    query = sql.select(columns, condition, from_obj=src)
    results = []
    artist_credit_ids = set()
    release_ids = set()
    release_group_ids = set()
    for row in conn.execute(query):
        results.append(dict(row))
        artist_credit_ids.add(row['recording_artist_credit'])
        if load_releases:
            release_ids.add(row['release_rid'])
            artist_credit_ids.add(row['release_artist_credit'])
            artist_credit_ids.add(row['track_artist_credit'])
            if load_release_groups:
                release_group_ids.add(row['release_group_rid'])

    if load_releases:
        releases = _load_release_meta(conn, release_ids)
        release_events = _load_release_events(conn, release_ids)
        for row in results:
            r_id = row.pop('release_rid')
            row.update(releases[r_id])
            row['release_events'] = release_events.get(r_id, {})

        if load_release_groups:
            release_groups = _load_release_groups(conn, release_group_ids)
            for row in results:
                rg_id = row.pop('release_group_rid')
                row.update(release_groups[rg_id])
                artist_credit_ids.add(row['release_group_artist_credit'])

    artists = _load_artists(conn, artist_credit_ids)
    for row in results:
        row['recording_artists'] = artists[row.pop('recording_artist_credit')]
        if load_releases:
            row['release_artists'] = artists[row.pop('release_artist_credit')]
            row['track_artists'] = artists[row.pop('track_artist_credit')]
            if load_release_groups:
                row['release_group_artists'] = artists[row.pop('release_group_artist_credit')]
    return results


def lookup_recording_metadata(conn, mbids):
    """
    Lookup MusicBrainz metadata for the specified MBIDs.
    """
    if not mbids:
        return {}
    src = schema.mb_recording.join(schema.mb_artist_credit)
    query = sql.select(
        [
            schema.mb_recording.c.gid,
            schema.mb_recording.c.name,
            schema.mb_recording.c.length,
            schema.mb_recording.c.comment,
            schema.mb_artist_credit.c.name.label('artist_name'),
        ],
        schema.mb_recording.c.gid.in_(mbids),
        from_obj=src)
    results = {}
    for row in conn.execute(query):
        result = dict(row)
        result['length'] = (result['length'] or 0) / 1000
        results[row['gid']] = result
    return results


def cluster_track_names(names):
    tokenized_names = [set([i.lower() for i in re.findall("(\w+)", n)]) for n in names]
    stats = {}
    for tokens in tokenized_names:
        for token in tokens:
            stats[token] = stats.get(token, 0) + 1
    if not stats:
        return
    top_words = set()
    max_score = max(stats.values())
    threshold = 0.7 * max_score
    for token, score in stats.items():
        if score > threshold:
            top_words.add(token)
    results = []
    for i, tokens in enumerate(tokenized_names):
        if not tokens:
            continue
        score = 1.0 * sum([float(stats[t]) / max_score for t in tokens if t in top_words]) / len(tokens)
        if score > 0.8:
            results.append((score, i))
    if not results:
        return
    results.sort(reverse=True)
    max_score = results[0][0]
    for score, i in results:
        if score > max_score * 0.8:
            yield i


def find_puid_mbids(conn, puid, min_duration, max_duration):
    """
    Find MBIDs for MusicBrainz tracks that are linked to the given PUID and
    have duration within the given range
    """
    src = schema.mb_puid
    src = src.join(schema.mb_recording_puid, schema.mb_recording_puid.c.puid == schema.mb_puid.c.id)
    src = src.join(schema.mb_recording, schema.mb_recording.c.id == schema.mb_recording_puid.c.recording)
    src = src.join(schema.mb_artist_credit, schema.mb_artist_credit.c.id == schema.mb_recording.c.artist_credit)
    condition = sql.and_(
        schema.mb_puid.c.puid == puid,
        sql.or_(
            schema.mb_recording.c.length.between(min_duration * 1000, max_duration * 1000),
            schema.mb_recording.c.length == None
        )
    )
    columns = [
        schema.mb_recording.c.gid,
        schema.mb_recording.c.name,
        schema.mb_artist_credit.c.name.label('artist')
    ]
    query = sql.select(columns, condition, from_obj=src).order_by(schema.mb_recording.c.id)
    rows = conn.execute(query).fetchall()
    good_group = cluster_track_names(r['name'] + ' ' + r['artist'] for r in rows)
    return [rows[i]['gid'] for i in good_group]


def resolve_mbid_redirect(conn, mbid):
    src = schema.mb_recording
    src = src.join(schema.mb_recording_gid_redirect, schema.mb_recording_gid_redirect.c.new_id == schema.mb_recording.c.id)
    condition = schema.mb_recording_gid_redirect.c.gid == mbid
    columns = [schema.mb_recording.c.gid]
    query = sql.select(columns, condition, from_obj=src)
    new_mbid = conn.execute(query).scalar()
    return new_mbid or mbid

