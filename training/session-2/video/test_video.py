"""Regression checks for lesson timing and publication provenance."""
import hashlib
import json
from pathlib import Path
import random
import tempfile
import unittest

from build_video import chapter_timing, write_ass, make_plan
from publish_video import publish, ASSETS
from synthesize import complete_word_timings


class WordBoundaryTests(unittest.TestCase):
    def test_zero_duration_clitic_uses_next_measured_boundary(self):
        words = [{'start': 38.479375, 'end': 38.479375, 'text': 'б'},
                 {'start': 38.569583, 'end': 39.1, 'text': 'відрізнятися'}]
        complete_word_timings(words, 40)
        self.assertEqual(words[0]['start'], 38.479375)
        self.assertEqual(words[0]['end'], words[1]['start'])
        self.assertEqual(words[0]['serviceDuration'], 0)
        self.assertEqual(words[0]['endSource'], 'next-word-start')

    def test_missing_or_invalid_boundaries_are_not_guessed(self):
        for ranges in [[(1, 1)], [(1, 1), (1, 2)], [(1, .5)],
                       [(2, 3), (1, 2)], [(float('nan'), 2)], [(1, 41)]]:
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                complete_word_timings([{'start': a, 'end': b} for a, b in ranges], 40)

    def test_normal_boundary_is_unchanged(self):
        words = [{'start': 1.2, 'end': 1.7, 'text': 'слово'}]
        complete_word_timings(words, 2)
        self.assertEqual(words, [{'start': 1.2, 'end': 1.7, 'text': 'слово'}])


class TimingTests(unittest.TestCase):
    def test_full_chapters_preserve_speech_and_exact_frames(self):
        rng = random.Random(2026)
        for _ in range(200):
            durations = [rng.uniform(5, 80) for _ in range(rng.randint(1, 12))]
            target = round(sum(durations) + len(durations) * 3 + rng.uniform(0, 60), 1)
            speed, lengths = chapter_timing(durations, target)
            self.assertLessEqual(speed, 1.12)
            self.assertEqual(sum(round(n * 10) for n in lengths), round(target * 10))
            for voice, length in zip(durations, lengths):
                self.assertGreaterEqual(length + 1e-8, voice / speed + .9)

    def test_overlong_narration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Shorten the script'):
            chapter_timing([100, 100], 120)

    def test_subtitle_rollover_and_literal_braces(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'captions.ass'
            write_ass(p, [{'start': 59.999, 'end': 61.22, 'text': '{code}\nnext'}])
            text = p.read_text(encoding='utf-8-sig')
            self.assertIn('0:01:00.00,0:01:01.22', text)
            self.assertIn('(code)\\Nnext', text)

    def test_stale_script_cannot_reuse_narration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'script.json').write_text('{}', encoding='utf-8')
            (root / 'manifest.json').write_text(json.dumps({'segments': [], 'sourceSha256': 'outdated'}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'current script'):
                make_plan(root / 'script.json', root, root)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        plan = {'duration': 7200, 'chapters': [], 'segments': []}
        (self.root / 'timeline.json').write_text(json.dumps(plan), encoding='utf-8')
        self.report = {'durationSeconds': 7200, 'frames': 72000, 'fullDecodePass': True,
                       'timelineSha256': self.hash('timeline.json'), 'assets': {}}
        for name in ASSETS:
            (self.root / name).write_bytes(b'fixture')
            self.report['assets'][name] = self.hash(name)

    def hash(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def report_file(self):
        (self.root / 'verification.json').write_text(json.dumps(self.report), encoding='utf-8')

    def test_changed_media_blocks_publication(self):
        self.report_file()
        (self.root / ASSETS[0]).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed video asset'):
            publish(self.root, self.root / 'public')
        self.assertFalse((self.root / 'public').exists())

    def test_changed_timeline_blocks_publication(self):
        self.report_file()
        (self.root / 'timeline.json').write_text(json.dumps({'duration': 7200, 'chapters': ['changed']}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale'):
            publish(self.root, self.root / 'public')

    def test_decode_failure_blocks_publication(self):
        self.report['fullDecodePass'] = False
        self.report_file()
        with self.assertRaisesRegex(ValueError, 'stale'):
            publish(self.root, self.root / 'public')


if __name__ == '__main__':
    unittest.main()
