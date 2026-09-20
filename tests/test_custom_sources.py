import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import custom_sources as sources


class CustomSourceTests(unittest.TestCase):
    def test_private_addresses_rejected(self):
        for ip in ('127.0.0.1','10.1.2.3','169.254.169.254','::1'):
            with patch('custom_sources.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]):
                with self.assertRaises(ValueError):sources.public_url('https://example.test/')
    def test_add_persists_and_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(sources,'FILE',Path(folder)/'sources.json'),patch('custom_sources.public_url',side_effect=lambda u:u):
            sources.add('Новости','https://example.test/rss','rss')
            self.assertEqual(len(sources.load()),1)
            with self.assertRaises(ValueError):sources.add('Другие','https://example.test/rss','rss')
    def test_feed_enters_real_collection_without_treating_excerpt_as_full_text(self):
        raw=b'<rss><channel><item><title>News</title><link>https://example.test/news/1</link><description>Summary only</description></item></channel></rss>'
        config=[{'id':'1','name':'Test','url':'https://example.test/rss','kind':'rss'}]
        with patch('custom_sources.load',return_value=config),patch('custom_sources.fetch',return_value=(raw,'utf-8','application/rss+xml')):
            docs,status=sources.collect()
        self.assertEqual(len(docs),1);self.assertEqual(docs[0].body,'');self.assertTrue(docs[0].in_perimeter);self.assertEqual(status[0]['status'],'ok')
