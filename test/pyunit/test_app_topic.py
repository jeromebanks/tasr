'''
Created on Apr 8, 2014

@author: cmills
'''

from tasr_test import TASRTestCase
from tasr.headers import SchemaHeaderBot, SubjectHeaderBot

import unittest
from webtest import TestApp
import StringIO
import tasr.app

APP = tasr.app.TASR_APP
APP.set_config_mode('local')


class TestTASRTopicApp(TASRTestCase):
    '''These tests check that the TASR native REST API (including the get by ID
    calls) are working as expected.  This does not check the S+V API calls.
    '''

    def setUp(self):
        self.event_type = "gold"
        fix_rel_path = "schemas/%s.avsc" % (self.event_type)
        self.avsc_file = TASRTestCase.get_fixture_file(fix_rel_path, "r")
        self.schema_str = self.avsc_file.read()
        self.tasr_app = TestApp(APP)
        self.url_prefix = 'http://%s:%s/tasr' % (APP.config.host,
                                                 APP.config.port)
        self.topic_url = '%s/topic/%s' % (self.url_prefix, self.event_type)
        self.content_type = 'application/json; charset=utf8'
        # clear out all the keys before beginning -- careful!
        APP.ASR.redis.flushdb()

    def tearDown(self):
        # this clears out redis after each test -- careful!
        APP.ASR.redis.flushdb()

    def abort_diff_status(self, resp, code):
        self.assertEqual(code, resp.status_code,
                         u'Non-%s status code: %s' % (code, resp.status_code))

    def register_schema(self, schema_str, expect_errors=False):
        return self.tasr_app.request(self.topic_url, method='PUT',
                                     expect_errors=expect_errors,
                                     content_type=self.content_type,
                                     body=schema_str)

    def test_get_all_topics(self):
        '''GET /tasr/topic - as expected'''
        # reg two vers for target topic and one for an alt topic
        self.register_schema(self.schema_str)
        schema_str_2 = self.schema_str.replace('tagged.events',
                                               'tagged.events.alt', 1)
        self.register_schema(schema_str_2)
        alt_topic = 'bob'
        alt_url = '%s/topic/%s' % (self.url_prefix, alt_topic)
        self.tasr_app.request(alt_url, method='PUT',
                              content_type=self.content_type,
                              body=self.schema_str)
        # now get all with versions and check the headers
        url = "%s/topic" % (self.url_prefix)
        resp = self.tasr_app.request(url, method='GET')
        self.abort_diff_status(resp, 200)
        # we expect a list of SubjectMetadata objects here
        meta_dict = SubjectHeaderBot.extract_metadata(resp)
        self.assertEqual(2, meta_dict[self.event_type].current_version,
                         'bad ver')
        self.assertEqual(1, meta_dict[alt_topic].current_version, 'bad ver')
        # lastly check the body
        buff = StringIO.StringIO(resp.body)
        group_names = []
        for topic_line in buff:
            group_names.append(topic_line.strip())
        buff.close()
        self.assertListEqual(sorted(group_names), sorted(meta_dict.keys()),
                             'Expected group_names in body to match headers.')

    def test_register_schema(self):
        '''PUT /tasr/topic/<topic name> - as expected'''
        resp = self.register_schema(self.schema_str)
        self.abort_diff_status(resp, 201)
        smeta = SchemaHeaderBot.extract_metadata(resp)
        self.assertIn(self.event_type, smeta.group_names, 'event_type missing')
        self.assertEqual(1, smeta.group_version(self.event_type), 'bad ver')
        self.assertTrue(smeta.group_timestamp(self.event_type), 'missing ts')

    def test_reg_fail_on_empty_schema(self):
        '''PUT /tasr/topic/<topic name> - empty schema'''
        resp = self.register_schema(None, expect_errors=True)
        self.abort_diff_status(resp, 400)

    def test_reg_fail_on_invalid_schema(self):
        '''PUT /tasr/topic/<topic name> - bad schema'''
        bad_schema_str = "%s }" % self.schema_str
        resp = self.register_schema(bad_schema_str, expect_errors=True)
        self.abort_diff_status(resp, 400)

    def test_reg_fail_on_bad_content_type(self):
        '''PUT /tasr/topic/<topic name> - bad Content-Type'''
        resp = self.tasr_app.request(self.topic_url, method='PUT',
                                     content_type='text/plain; charset=utf8',
                                     expect_errors=True,
                                     body=self.schema_str)
        self.abort_diff_status(resp, 406)

    def test_reg_and_rereg(self):
        '''PUT /tasr/topic/<topic name> - multiple calls, same schema'''
        resp = self.register_schema(self.schema_str)
        self.abort_diff_status(resp, 201)
        smeta = SchemaHeaderBot.extract_metadata(resp)
        self.assertEqual(1, smeta.group_version(self.event_type), 'bad ver')

        # on the re-registration, we should get the same version back
        resp2 = self.register_schema(self.schema_str)
        self.abort_diff_status(resp2, 200)
        smeta2 = SchemaHeaderBot.extract_metadata(resp2)
        self.assertEqual(1, smeta2.group_version(self.event_type),
                         'Re-reg produced a different group version.')

    def test_multi_topic_reg(self):
        '''PUT /tasr/topic/<topic name> - multiple group_names, same schema'''
        put_resp = self.register_schema(self.schema_str)
        self.abort_diff_status(put_resp, 201)
        smeta = SchemaHeaderBot.extract_metadata(put_resp)
        self.assertEqual(1, smeta.group_version(self.event_type), 'bad ver')

        alt_topic = 'bob'
        alt_url = '%s/topic/%s' % (self.url_prefix, alt_topic)
        put_resp2 = self.tasr_app.request(alt_url, method='PUT',
                                          content_type=self.content_type,
                                          body=self.schema_str)
        self.abort_diff_status(put_resp2, 201)
        smeta2 = SchemaHeaderBot.extract_metadata(put_resp2)
        self.assertEqual(1, smeta2.group_version(alt_topic), 'bad ver')

        # getting by ID gives us all topic associations in headers
        id_url = "%s/id/%s" % (self.url_prefix, smeta.sha256_id)
        get_resp = self.tasr_app.request(id_url, method='GET')
        smeta3 = SchemaHeaderBot.extract_metadata(get_resp)
        self.assertEqual(1, smeta3.group_version(self.event_type), 'bad ver')
        self.assertEqual(1, smeta3.group_version(alt_topic), 'bad ver')

    def test_get_latest_1(self):
        '''GET /tasr/topic/<topic name> - as expected'''
        put_resp = self.register_schema(self.schema_str)
        # the canonicalized form returned has normalized whitespace
        canonicalized_schema_str = put_resp.body
        # now pull it back with a GET
        get_resp = self.tasr_app.request(self.topic_url, method='GET')
        self.abort_diff_status(get_resp, 200)
        smeta = SchemaHeaderBot.extract_metadata(get_resp)
        self.assertEqual(1, smeta.group_version(self.event_type), 'bad ver')
        self.assertEqual(canonicalized_schema_str, get_resp.body,
                         u'Unexpected body: %s' % get_resp.body)

    def test_get_latest_2(self):
        '''GET /tasr/topic/<topic name>/latest - as expected'''
        put_resp = self.register_schema(self.schema_str)
        # the canonicalized form returned has normalized whitespace
        canonicalized_schema_str = put_resp.body
        # now pull it back with a GET
        get_url = '%s/latest' % self.topic_url
        get_resp = self.tasr_app.request(get_url, method='GET')
        self.abort_diff_status(get_resp, 200)
        smeta = SchemaHeaderBot.extract_metadata(get_resp)
        self.assertEqual(1, smeta.group_version(self.event_type), 'bad ver')
        self.assertEqual(canonicalized_schema_str, get_resp.body,
                         u'Unexpected body: %s' % get_resp.body)

    def test_reg_50_and_get_by_version(self):
        '''GET /tasr/topic/<topic name>/version/<version> - as expected'''
        schemas = []
        # add a bunch of versions for our topic
        for v in range(1, 50):
            ver_schema_str = self.schema_str.replace('tagged.events',
                                                     'tagged.events.%s' % v, 1)
            put_resp = self.register_schema(ver_schema_str)
            # the canonicalized form returned has normalized whitespace
            canonicalized_schema_str = put_resp.body
            schemas.append(canonicalized_schema_str)
            self.abort_diff_status(put_resp, 201)

        # step through and request each version by version number
        for v in range(1, 50):
            query = "%s/version/%s" % (self.topic_url, v)
            get_resp = self.tasr_app.request(query, method='GET')
            self.abort_diff_status(get_resp, 200)
            self.assertEqual(schemas[v - 1], get_resp.body,
                             u'Unexpected body: %s' % get_resp.body)

    def test_get_for_topic_and_version_fail_on_bad_version(self):
        '''GET /tasr/topic/<topic name>/version/<version> - fail on bad ver'''
        put_resp = self.register_schema(self.schema_str)
        smeta = SchemaHeaderBot.extract_metadata(put_resp)
        self.assertEqual(1, smeta.group_version(self.event_type), 'bad ver')
        bad_ver = smeta.group_version(self.event_type) + 1
        url = "%s/version/%s" % (self.topic_url, bad_ver)
        get_resp = self.tasr_app.request(url, method='GET', expect_errors=True)
        self.abort_diff_status(get_resp, 404)

    def test_get_for_stale_version(self):
        '''GET /tasr/topic/<topic name>/version/<version> - 1 schema, 2 vers'''
        put_resp = self.register_schema(self.schema_str)
        # the canonicalized form returned has normalized whitespace
        canonicalized_schema_str = put_resp.body
        self.abort_diff_status(put_resp, 201)
        schema_str_2 = self.schema_str.replace('tagged.events',
                                               'tagged.events.alt', 1)
        put_resp2 = self.register_schema(schema_str_2)
        self.abort_diff_status(put_resp2, 201)
        put_resp3 = self.register_schema(self.schema_str)
        smeta = SchemaHeaderBot.extract_metadata(put_resp3)
        self.assertEqual(3, smeta.group_version(self.event_type), 'bad ver')

        # now get version 1 -- should be same schema, but diff ver in headers
        url = "%s/version/%s" % (self.topic_url, 1)
        get_resp = self.tasr_app.request(url, method='GET', expect_errors=True)
        self.abort_diff_status(get_resp, 200)
        self.assertEqual(canonicalized_schema_str, get_resp.body,
                         u'Unexpected body: %s' % get_resp.body)
        smeta = SchemaHeaderBot.extract_metadata(get_resp)
        self.assertEqual(1, smeta.group_version(self.event_type), 'bad ver')


if __name__ == "__main__":
    SUITE = unittest.TestLoader().loadTestsFromTestCase(TestTASRTopicApp)
    unittest.TextTestRunner(verbosity=2).run(SUITE)
