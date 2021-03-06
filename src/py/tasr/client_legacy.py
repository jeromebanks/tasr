'''
Created on May 6, 2014

@author: cmills

The idea here is to provide client-side functions to interact with the TASR
repo.  We use the requests package here.  We provide both stand-alone functions
and a class with methods.  The class is easier if you are using non-default
values for the host or port.
'''

import requests
import tasr.app
from tasr.registered_schema import RegisteredAvroSchema
from tasr.headers import SubjectHeaderBot, SchemaHeaderBot
from tasr.client import TASRError, reg_schema_from_url

APP = tasr.app.TASR_APP
APP.set_config_mode('local')
TASR_HOST = APP.config.host
TASR_PORT = APP.config.port
TIMEOUT = 2  # seconds


def get_active_topics(host=TASR_HOST, port=TASR_PORT, timeout=TIMEOUT):
    ''' GET /tasr/active_topics
    Retrieves available metadata for active topics (i.e. -- groups) with
    registered schemas.  A dict of <topic name>:<topic metadata> is returned.
    '''
    url = 'http://%s:%s/tasr/active_topics' % (host, port)
    resp = requests.get(url, timeout=timeout)
    if resp == None:
        raise TASRError('Timeout for request to %s' % url)
    if not 200 == resp.status_code:
        raise TASRError('Failed request to %s (status code: %s)' %
                        (url, resp.status_code))
    topic_metas = SubjectHeaderBot.extract_metadata(resp)
    return topic_metas


def get_all_topics(host=TASR_HOST, port=TASR_PORT, timeout=TIMEOUT):
    ''' GET /tasr/topic
    Retrieves available metadata for all the topics (i.e. -- groups) with
    registered schemas.  A dict of <topic name>:<topic metadata> is returned.
    '''
    url = 'http://%s:%s/tasr/topic' % (host, port)
    resp = requests.get(url, timeout=timeout)
    if resp == None:
        raise TASRError('Timeout for request to %s' % url)
    if not 200 == resp.status_code:
        raise TASRError('Failed request to %s (status code: %s)' %
                        (url, resp.status_code))
    topic_metas = SubjectHeaderBot.extract_metadata(resp)
    return topic_metas


def register_schema(topic_name, schema_str, host=TASR_HOST,
                          port=TASR_PORT, timeout=TIMEOUT):
    ''' PUT /tasr/topic/<topic name>
    Register a schema string for a topic.  Returns a SchemaMetadata object
    with the topic-version, topic-timestamp and ID metadata.
    '''
    url = 'http://%s:%s/tasr/topic/%s' % (host, port, topic_name)
    headers = {'content-type': 'application/json; charset=utf8', }
    rs = reg_schema_from_url(url, method='PUT', data=schema_str,
                             headers=headers, timeout=timeout)
    return rs


def get_latest_schema(topic_name, host=TASR_HOST,
                      port=TASR_PORT, timeout=TIMEOUT):
    ''' GET /tasr/topic/<topic name>
    Retrieve the latest schema registered for the given topic name.  Returns a
    RegisteredSchema object back.
    '''
    return get_schema_version(topic_name, None, host, port, timeout)


def get_schema_version(topic_name, version, host=TASR_HOST,
                       port=TASR_PORT, timeout=TIMEOUT):
    ''' GET /tasr/topic/<topic name>/version/<version>
    Retrieve a specific schema registered for the given topic name identified
    by a version (a positive integer).  Returns a RegisteredSchema object.
    '''
    url = ('http://%s:%s/tasr/topic/%s/version/%s' %
           (host, port, topic_name, version))
    return reg_schema_from_url(url, timeout=timeout,
                               err_404='No such version.')


def schema_for_id_str(id_str, host=TASR_HOST,
                          port=TASR_PORT, timeout=TIMEOUT):
    ''' GET /tasr/id/<ID string>
    Retrieves a schema that has been registered for at least one topic name as
    identified by a hash-based ID string.  The ID string is a base64 encoded
    byte sequence, starting with a 1-byte ID type and followed by fingerprint
    bytes for the ID type.  For example, with an SHA256-based ID, a fingerprint
    is 32 bytes in length, so there would be 33 ID bytes, which would produce
    an ID string of length 44 once base64-encoded.  The MD5-based IDs are 17
    bytes (1 + 16), producing ID strings of length 24.  A RegisteredSchema
    object is returned.
    '''
    url = 'http://%s:%s/tasr/id/%s' % (host, port, id_str)
    return reg_schema_from_url(url, timeout=timeout,
                               err_404='No schema for id.')


def schema_for_schema_str(schema_str, object_on_miss=False,
                              host=TASR_HOST, port=TASR_PORT, timeout=TIMEOUT):
    ''' POST /tasr/schema
    In essence this is very similar to the schema_for_id_str, but with the
    calculation of the ID string being moved to the server.  That is, the
    client POSTs the schema JSON itself, the server canonicalizes it, then
    calculates the SHA256-based ID string for what was sent, then looks for
    a matching schema based on that ID string.  This allows clients that do not
    know how to canonicalize or hash the schemas to find the metadata (is it
    registered, what version does it have for a topic) with what they have.

    A RegisteredSchema object is returned if the schema string POSTed has been
    registered for one or more topics.

    If the schema string POSTed has yet to be registered for a topic and the
    object_on_miss flag is True, a RegisteredSchema calculated for the POSTed
    schema string is returned (it will have no topic-versions as there are
    none).  This provides an easy way for a client to get the ID strings to
    use for subsequent requests.

    If the object_on_miss flag is False (the default), then a request for a
    previously unregistered schema will raise a TASRError.
    '''
    url = 'http://%s:%s/tasr/schema' % (host, port)
    headers = {'content-type': 'application/json; charset=utf8', }
    resp = requests.post(url, data=schema_str, headers=headers,
                         timeout=timeout)
    if resp == None:
        raise TASRError('Timeout for request to %s' % url)
    if 200 == resp.status_code:
        # success -- return a normal reg schema
        ras = RegisteredAvroSchema()
        ras.schema_str = resp.context
        schema_meta = SchemaHeaderBot.extract_metadata(resp)
        ras.update_from_schema_metadata(schema_meta)
        return ras
    elif 404 == resp.status_code and object_on_miss:
        ras = RegisteredAvroSchema()
        ras.schema_str = schema_str
        schema_meta = SchemaHeaderBot.extract_metadata(resp)
        ras.update_from_schema_metadata(schema_meta)
        return ras
    raise TASRError('Schema not registered to any topics.')


#############################################################################
# Wrapped in a class
#############################################################################


class TASRLegacyClient(object):
    '''An object means you only need to specify the host settings once.
    '''
    def __init__(self, host=TASR_HOST, port=TASR_PORT, timeout=TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout

    # topic calls
    def get_active_topics(self):
        '''Returns a dict of <topic name>:<metadata> for active topics.'''
        return get_active_topics(self.host, self.port, self.timeout)

    def get_all_topics(self):
        '''Returns a dict of <topic name>:<metadata> for all topics.'''
        return get_all_topics(self.host, self.port, self.timeout)

    # schema calls
    def register_schema(self, topic_name, schema_str):
        '''Register a schema for a topic'''
        return register_schema(topic_name, schema_str)

    def get_latest_schema(self, topic_name):
        '''Get the latest schema registered for a topic'''
        return get_latest_schema(topic_name,
                                 self.host, self.port, self.timeout)

    def get_schema_version(self, topic_name, version=None):
        '''Get a schema by version for the topic'''
        return get_schema_version(topic_name, version,
                                  self.host, self.port, self.timeout)

    def schema_for_id_str(self, id_str):
        '''Get a schema identified by an ID str.'''
        return schema_for_id_str(id_str,
                                     self.host, self.port, self.timeout)

    def schema_for_schema_str(self, schema_str):
        '''Get a schema object using a (non-canonical) schema string.'''
        return schema_for_schema_str(schema_str,
                                         self.host, self.port, self.timeout)
