# Copyright (C) 2011 Lukas Lalinsky
# Distributed under the MIT license, see the LICENSE file for details.

import logging
import chromaprint
from contextlib import closing
from sqlalchemy import sql
from acoustid import tables as schema, const

logger = logging.getLogger(__name__)


FINGERPRINT_VERSION = 1
PARTS = ((1, 20), (21, 100))
PART_SEARCH_SQL = """
SELECT f.id, f.track_id, t.gid AS track_gid, score FROM (
    SELECT id, track_id, acoustid_compare2(fingerprint, query, %(max_offset)s) AS score
    FROM fingerprint, (SELECT %(fp)s::int4[] AS query) q
    WHERE
        length BETWEEN %(length)s - %(max_length_diff)s AND %(length)s + %(max_length_diff)s AND
        subarray(acoustid_extract_query(query), %(part_start)s, %(part_length)s) && acoustid_extract_query(fingerprint)
) f JOIN track t ON f.track_id=t.id WHERE f.score > %(min_score)s ORDER BY f.score DESC, f.id
"""


def decode_fingerprint(fingerprint_string):
    """Decode a compressed and base64-encoded fingerprint"""
    fingerprint, version = chromaprint.decode_fingerprint(fingerprint_string)
    if version == FINGERPRINT_VERSION:
        return fingerprint


def lookup_fingerprint(conn, fp, length, good_enough_score, min_score, fast=False, max_offset=0):
    """Search for a fingerprint in the database"""
    matched = []
    best_score = 0.0
    for part_start, part_length in PARTS:
        params = dict(fp=fp, length=length, part_start=part_start,
            part_length=part_length, max_length_diff=const.FINGERPRINT_MAX_LENGTH_DIFF,
            min_score=min_score, max_offset=max_offset)
        with closing(conn.execute(PART_SEARCH_SQL, params)) as result:
            for row in result:
                matched.append(row)
                if row['score'] >= best_score:
                    best_score = row['score']
        if best_score > good_enough_score:
            break
    return matched


class FingerprintSearcher(object):

    def __init__(self, db, idx=None):
        self.db = db
        self.idx = idx
        self.min_score = const.TRACK_GROUP_MERGE_THRESHOLD
        self.max_length_diff = const.FINGERPRINT_MAX_LENGTH_DIFF
        self.max_offset = const.TRACK_MAX_OFFSET

    def _search_index(self, fp, length):
        # index search
        fp_query = self.db.execute(sql.select([sql.func.acoustid_extract_query(fp)])).scalar()
        with closing(self.idx.connect()) as idx:
            results = idx.search(fp_query)
            if not results:
                return []
            min_score = results[0].score * 0.1 # at least 10% of the top score
            candidate_ids = [r.id for r in results if r.score > min_score]
            if not candidate_ids:
                return []
        # construct the subquery
        f_columns = [
            schema.fingerprint.c.id,
            schema.fingerprint.c.track_id,
            sql.func.acoustid_compare2(schema.fingerprint.c.fingerprint, fp,
                                       self.max_offset).label('score'),
        ]
        f_where = sql.and_(
            schema.fingerprint.c.id.in_(candidate_ids),
            schema.fingerprint.c.length.between(length - self.max_length_diff,
                                                length + self.max_length_diff))
        f = sql.select(f_columns, f_where).alias('f')
        # construct the main query
        columns = [f.c.id, f.c.track_id, schema.track.c.gid.label('track_gid'), f.c.score]
        src = f.join(schema.track, schema.track.c.id == f.c.track_id)
        query = sql.select(columns, f.c.score > self.min_score, src,
                           order_by=[f.c.score.desc(), f.c.id])
        # database scoring
        return self.db.execute(query).fetchall()

    def _search_database(self, fp, index):
        return lookup_fingerprint(self.db, fp, length, const.TRACK_MERGE_THRESHOLD,
                                  self.min_score, max_offset=self.max_offset)

    def search(self, fp, length):
        import time
        t = time.time()
        if self.idx is not None:
            matches = self._search_index(fp, length)
        else:
            matches = self._search_database(fp, length)
        print time.time() - t
        return matches


def insert_fingerprint(conn, data, submission_id=None, source_id=None):
    """
    Insert a new fingerprint into the database
    """
    with conn.begin():
        insert_stmt = schema.fingerprint.insert().values({
            'fingerprint': data['fingerprint'],
            'length': data['length'],
            'bitrate': data.get('bitrate'),
            'format_id': data.get('format_id'),
            'track_id': data['track_id'],
            'submission_count': 1,
        })
        id = conn.execute(insert_stmt).inserted_primary_key[0]
        if submission_id and source_id:
            insert_stmt = schema.fingerprint_source.insert().values({
                'fingerprint_id': id,
                'submission_id': submission_id,
                'source_id': source_id,
            })
            conn.execute(insert_stmt)
    logger.debug("Inserted fingerprint %r", id)
    return id


def inc_fingerprint_submission_count(conn, id, submission_id=None, source_id=None):
    update_stmt = schema.fingerprint.update().where(schema.fingerprint.c.id == id)
    conn.execute(update_stmt.values(submission_count=sql.text('submission_count+1')))
    if submission_id and source_id:
        insert_stmt = schema.fingerprint_source.insert().values({
            'fingerprint_id': id,
            'submission_id': submission_id,
            'source_id': source_id,
        })
        conn.execute(insert_stmt)
    return True

