"""E2E-style tests for mobile/main.py: PlaylistScreen, popups, LuisterApp."""

import os
import sys
import time
import types

import pytest
from kivy.base import EventLoop
from kivy.tests.common import UnitTestTouch

from tests.helpers_mobile import load_mobile_main

m = load_mobile_main()


class FakeEvent:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakeClock:
    """Runs scheduled callbacks immediately."""

    def __init__(self):
        self.intervals = []

    def schedule_once(self, fn, timeout=0):
        fn(0)
        return FakeEvent()

    def schedule_interval(self, fn, timeout=0):
        ev = FakeEvent()
        self.intervals.append((fn, ev))
        return ev


class SyncThread:
    def __init__(self, target=None, daemon=None, **kw):
        self.target = target

    def start(self):
        self.target()


class FakeSound:
    def __init__(self, length=100.0, pos=0.0):
        self.length = length
        self.pos = pos
        self.volume = 1.0
        self.calls = []

    def play(self):
        self.calls.append('play')

    def stop(self):
        self.calls.append('stop')

    def seek(self, p):
        self.calls.append(('seek', p))

    def unload(self):
        self.calls.append('unload')


def touch(widget):
    """Simulate a real tap in the middle of a widget."""
    t = UnitTestTouch(*widget.to_window(*widget.center))
    t.touch_down()
    t.touch_up()


def click(btn):
    btn.dispatch('on_release')


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(m, 'Clock', FakeClock())
    monkeypatch.setattr(m.threading, 'Thread', SyncThread)
    monkeypatch.setattr(m, 'platform', 'linux')
    a = m.LuisterApp()
    root = a.build()
    a.root = root
    m.App._running_app = a
    yield a
    m.App._running_app = None


def make_audio(dirpath, name, mtime=None):
    p = dirpath / name
    p.write_bytes(b'x')
    if mtime:
        os.utime(p, (mtime, mtime))
    return str(p)


# ---------------------------------------------------------------- Playlist
def test_playlist_screen_buttons_and_refresh(app, monkeypatch):
    ps = app.playlist_screen
    ps._update_bg()
    calls = []
    monkeypatch.setattr(app, 'open_folder', lambda: calls.append('open'))
    monkeypatch.setattr(app, 'scan_music_directories', lambda: calls.append('scan'))
    monkeypatch.setattr(app, 'clear_playlist', lambda: calls.append('clear'))
    ps.add_files(None)
    ps.scan_music(None)
    ps.clear_playlist(None)
    assert calls == ['open', 'scan', 'clear']

    app.root.current = 'playlist'
    ps.go_back(None)
    assert app.root.current == 'main'

    paths = [f'/m/song{i}.mp3' for i in range(50)]
    ps.scroll.height = 100
    ps.refresh_playlist(paths, 25)
    assert ps.count_label.text == '50 tracks'
    assert len(ps.playlist_grid.children) == 50
    ps.refresh_playlist([], -1)
    assert ps.count_label.text == '0 tracks'

    # Scroll helper branches
    ps._scroll_to_current(0, 0)
    ps.scroll.height = 10000
    ps._scroll_to_current(1, 5)
    ps.scroll.height = 100
    ps._scroll_to_current(25, 50)
    ps._scroll_to_current(0, 50)
    ps._scroll_to_current(49, 50)


def test_playlist_no_running_app():
    m.App._running_app = None
    ps = m.PlaylistScreen(name='p')
    ps.go_back(None)
    ps.add_files(None)
    ps.scan_music(None)
    ps.clear_playlist(None)


# ---------------------------------------------------------------- YouTube
def test_youtube_popup_flow(app, monkeypatch):
    pop = m.YouTubeDownloadPopup()
    click(pop.download_btn)
    assert pop.status_label.text == 'Please enter a URL'

    got = []
    monkeypatch.setattr(app, 'download_youtube', lambda u, p: got.append(u))
    pop.url_input.text = '  http://y/x  '
    click(pop.download_btn)
    assert got == ['http://y/x'] and pop.download_btn.disabled

    pop.update_progress(40, 'Downloading... 40%')
    assert pop.progress_bar.value == 40
    pop.download_complete(False, 'bad')
    assert not pop.download_btn.disabled and pop.status_label.text == 'bad'
    pop.open()
    pop.download_complete(True, 'ok')
    pop.dismiss()

    m.App._running_app = None
    click(pop.download_btn)  # no app: nothing happens


def test_show_youtube_dialog(app):
    app.show_youtube_dialog()


class FakeYDL:
    files = []
    fail = None

    def __init__(self, opts):
        FakeYDL.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def download(self, urls):
        if FakeYDL.fail:
            raise FakeYDL.fail
        hook = FakeYDL.opts['progress_hooks'][0]
        hook({'status': 'downloading', 'total_bytes': 200, 'downloaded_bytes': 100})
        hook({'status': 'downloading', 'downloaded_bytes': 1})
        hook({'status': 'other'})
        hook({'status': 'finished'})
        lg = FakeYDL.opts['logger']
        lg.debug('d')
        lg.info('i')
        lg.warning('w')
        lg.error('e')
        for f in FakeYDL.files:
            (self_dir / f).write_bytes(b'x')


self_dir = None


def run_download(app, monkeypatch, tmp_path, files, fail=None, playing=False):
    global self_dir
    self_dir = app.config_manager.downloads_dir
    FakeYDL.files = files
    FakeYDL.fail = fail
    monkeypatch.setitem(sys.modules, 'yt_dlp', types.SimpleNamespace(YoutubeDL=FakeYDL))
    app.is_playing = playing
    monkeypatch.setattr(m, 'load_audio', lambda p, logger=None, on_complete=None: FakeSound())
    pop = m.YouTubeDownloadPopup()
    pop.open()
    app.download_youtube('http://y', pop)
    return pop


def test_download_success_plays(app, monkeypatch, tmp_path):
    pop = run_download(app, monkeypatch, tmp_path, ['a.m4a'])
    assert pop.status_label.text == 'Downloaded 1 file(s)'
    assert len(app.playlist) == 1 and app.is_playing


def test_download_success_already_playing_and_dupe(app, monkeypatch, tmp_path):
    existing = str(app.config_manager.downloads_dir / 'a.m4a')
    app.playlist = [existing]
    pop = run_download(app, monkeypatch, tmp_path, ['a.m4a'], playing=True)
    assert app.playlist == [existing]
    assert pop.status_label.text == 'Downloaded 1 file(s)'


def test_download_no_files(app, monkeypatch, tmp_path):
    pop = run_download(app, monkeypatch, tmp_path, [])
    assert pop.status_label.text == 'No files downloaded'


def test_download_error(app, monkeypatch, tmp_path):
    pop = run_download(app, monkeypatch, tmp_path, [], fail=RuntimeError('boom'))
    assert pop.status_label.text == 'Error: boom'


def test_download_import_error(app, monkeypatch):
    monkeypatch.setitem(sys.modules, 'yt_dlp', None)
    pop = m.YouTubeDownloadPopup()
    app.download_youtube('u', pop)
    assert pop.status_label.text == 'yt-dlp not installed'


# ---------------------------------------------------------------- Lyrics
def test_lyrics_popup_flow(app, monkeypatch, tmp_path):
    audio = make_audio(tmp_path, 'Artist - Song.mp3')
    long_title = 'T' * 50
    pop = m.LyricsPopup(song_title=long_title, file_path=audio)
    assert not pop.lyrics_label.text and pop.save_btn.disabled
    click(pop.save_btn)  # empty text -> early return

    monkeypatch.setattr(app, 'fetch_lyrics', lambda t, p: p.update_lyrics('la', 'st'))
    click(pop.fetch_btn)
    assert pop.lyrics_label.text == 'la' and not pop.save_btn.disabled
    pop.update_lyrics('', 'none')

    monkeypatch.setattr(app, 'transcribe_lyrics', lambda f, p: None)
    click(pop.transcribe_btn)
    assert pop.transcribe_btn.disabled

    pop.open()
    pop.lyrics_label.text = '[00:01.00]hi'
    app.playlist = [audio]
    app.current_index = 0
    app.sound = FakeSound()
    click(pop.save_btn)
    assert pop.status_label.text == 'Lyrics saved!'
    assert app.get_lyrics_for_track(audio) == '[00:01.00]hi'

    # existing lyrics are picked up by a new popup
    pop2 = m.LyricsPopup(song_title='s', file_path=audio)
    assert pop2.status_label.text == 'Lyrics loaded from file'
    # save failure
    monkeypatch.setattr(app, 'save_lyrics_for_track', lambda a, b: False)
    pop2.save_lyrics(None)
    assert pop2.status_label.text == 'Failed to save lyrics'

    # app.root missing in go_back
    monkeypatch.setattr(app, 'save_lyrics_for_track', lambda a, b: True)
    app.root = None
    pop2.save_lyrics(None)

    # no running app
    m.App._running_app = None
    pop2.save_lyrics(None)
    pop2.fetch_lyrics(None)
    pop2.transcribe_lyrics(None)
    pop3 = m.LyricsPopup(song_title='s', file_path=audio)
    assert pop3.lyrics_label.text == ''


def test_show_lyrics_popup(app, tmp_path):
    app.show_lyrics_popup('t', str(tmp_path / 'x.mp3'))


def test_lyrics_files_helpers(app, tmp_path, monkeypatch):
    p = app.get_lyrics_path('/a/b/we!ird:name?.mp3')
    assert p.name == 'weirdname.lrc'
    assert app.get_lyrics_for_track('/a/none.mp3') is None

    # read error
    app.save_lyrics_for_track('/a/z.mp3', 'x')
    monkeypatch.setattr(m.Path, 'read_text',
                        lambda self, **k: (_ for _ in ()).throw(OSError('no')))
    assert app.get_lyrics_for_track('/a/z.mp3') is None
    monkeypatch.undo()

    # save error + non-matching current track
    monkeypatch.setattr(m.Path, 'write_text',
                        lambda self, *a, **k: (_ for _ in ()).throw(OSError('no')))
    assert app.save_lyrics_for_track('/a/z.mp3', 'x') is False
    monkeypatch.undo()
    app.playlist = ['/q.mp3']
    app.current_index = 0
    assert app.save_lyrics_for_track('/a/z.mp3', 'x') is True


def test_parse_lrc(app):
    out = app.parse_lrc_lyrics(
        '\n[01:02.50]b\n[00:03]c\n[00:04.123]d\n[00:05.00]  \nplain\n')
    assert out == [(3.0, 'c'), (4.123, 'd'), (62.5, 'b')]


def test_parse_lrc_single_digit_fraction(app):
    # ".5" means half a second
    assert app.parse_lrc_lyrics('[00:01.5]a') == [(1.5, 'a')]


def test_load_lyrics_variants(app, tmp_path):
    a = make_audio(tmp_path, 'a.mp3')
    app.load_lyrics_for_current_track()  # no playlist
    app.playlist = [a]
    app.current_index = 0
    app.load_lyrics_for_current_track()  # no lyrics file
    assert not app._current_lyrics

    app.save_lyrics_for_track(a, '[00:01.00]one\n[00:05.00]two')
    assert len(app._current_lyrics) == 2

    app.save_lyrics_for_track(a, 'line1\nline2')
    assert app._plain_lyrics_lines == ['line1', 'line2']

    app.save_lyrics_for_track(a, 'only')
    assert app._plain_lyrics_lines == ['only']

    app.save_lyrics_for_track(a, '  \n ')
    assert app._plain_lyrics_lines == []


def test_update_lyrics_display(app):
    shown = []
    app.main_screen.update_lyrics = lambda c, n='': shown.append((c, n))
    app._current_lyrics = [(1.0, 'a'), (5.0, 'b')]
    app._current_lyrics_index = 1
    app.update_lyrics_display(0.0)
    assert shown[-1] == ('', 'a')
    app.update_lyrics_display(2.0)
    assert shown[-1] == ('a', 'b')
    app.update_lyrics_display(2.1)  # unchanged
    assert len(shown) == 2
    app.update_lyrics_display(9.0)
    assert shown[-1] == ('b', '')

    app._current_lyrics = []
    app._plain_lyrics_lines = ['x', 'y', 'z']
    app.sound = FakeSound(length=30)
    app.update_lyrics_display(0)
    assert shown[-1] == ('x', 'y')
    app.update_lyrics_display(29.9)
    assert shown[-1] == ('z', '')
    app.update_lyrics_display(29.9)

    app.sound = None
    app.update_lyrics_display(1)  # nothing

    app._current_lyrics = [(1.0, 'a')]
    app.main_screen.update_lyrics = lambda *a: (_ for _ in ()).throw(ValueError('x'))
    app.update_lyrics_display(3.0)  # exception swallowed


# ---------------------------------------------------------------- fetch
def run_fetch(app, monkeypatch, title, http):
    monkeypatch.setattr(m, 'http_get', http)
    pop = m.LyricsPopup(song_title=title, file_path='/x/a.mp3')
    app.fetch_lyrics(title, pop)
    return pop


def test_fetch_lyrics_ovh(app, monkeypatch):
    pop = run_fetch(app, monkeypatch, 'Artist - Song (Official Video)',
                    lambda url, headers=None, timeout=10: (200, {'lyrics': 'words'}))
    assert pop.lyrics_label.text == 'words'
    assert pop.status_label.text == 'Lyrics found!'


def test_fetch_lyrics_lrclib_fallback(app, monkeypatch):
    def http(url, headers=None, timeout=10):
        if 'ovh' in url:
            raise RuntimeError('down')
        return 200, [{'syncedLyrics': '[00:01.00]s', 'trackName': 'T'}]
    pop = run_fetch(app, monkeypatch, 'Artist - Song', http)
    assert pop.lyrics_label.text == '[00:01.00]s'


def test_fetch_lyrics_none(app, monkeypatch):
    pop = run_fetch(app, monkeypatch, 'Just a title', lambda *a, **k: (404, None))
    assert pop.status_label.text.startswith('No lyrics found')


def test_fetch_lyrics_lrclib_error(app, monkeypatch):
    def http(url, headers=None, timeout=10):
        raise RuntimeError('x')
    pop = run_fetch(app, monkeypatch, 'Artist – Song', http)
    assert pop.status_label.text.startswith('No lyrics found')


def test_fetch_lyrics_outer_error(app, monkeypatch):
    real_log = app.log

    def log(msg):
        if str(msg).startswith('Searching'):
            raise KeyError('q')
        real_log(msg)
    monkeypatch.setattr(app, 'log', log)
    pop = run_fetch(app, monkeypatch, 'Just', lambda *a, **k: (200, []))
    assert pop.status_label.text.startswith('Error:')


# ---------------------------------------------------------------- transcribe
def run_transcribe(app, monkeypatch, post, key='sk-x'):
    app.config_manager.openai_api_key = key
    monkeypatch.setattr(m, 'http_post_file', post)
    pop = m.LyricsPopup(song_title='s', file_path='/x/a.mp3')
    app.transcribe_lyrics('/x/a.mp3', pop)
    return pop


def test_transcribe_no_key(app, monkeypatch):
    pop = run_transcribe(app, monkeypatch, None, key='')
    assert pop.status_label.text.startswith('No API key')


def test_transcribe_success(app, monkeypatch):
    segs = {'segments': [{'start': 65.5, 'text': ' hello '}, {'start': 1, 'text': ' '}]}
    pop = run_transcribe(app, monkeypatch, lambda *a, **k: (200, segs))
    assert pop.lyrics_label.text == '[01:05.50]hello'
    assert pop.status_label.text == 'Transcribed 2 lines'


def test_transcribe_no_speech(app, monkeypatch):
    pop = run_transcribe(app, monkeypatch, lambda *a, **k: (200, {'segments': []}))
    assert pop.status_label.text == 'No speech detected in audio'


def test_transcribe_api_errors(app, monkeypatch):
    pop = run_transcribe(app, monkeypatch, lambda *a, **k: (500, None))
    assert pop.status_label.text == 'API error: 500'
    pop = run_transcribe(app, monkeypatch,
                         lambda *a, **k: (401, {'error': {'message': 'bad key'}}))
    assert pop.status_label.text == 'bad key'


def test_transcribe_exception(app, monkeypatch):
    def post(*a, **k):
        raise RuntimeError('net')
    pop = run_transcribe(app, monkeypatch, post)
    assert pop.status_label.text == 'Error: net'


def test_transcribe_sends_auth_header(app, monkeypatch):
    seen = {}

    def post(url, headers, *a, **k):
        seen['h'] = headers
        return 200, {'segments': []}
    run_transcribe(app, monkeypatch, post, key='sk-secret')
    assert seen['h']['Authorization'] == 'Bearer sk-secret'


# ---------------------------------------------------------------- Settings
def test_settings_popup(app):
    app.config_manager.openai_api_key = 'sk-old'
    pop = m.SettingsPopup()
    assert pop.api_input.text == 'sk-old'
    pop.open()
    pop.api_input.text = '  sk-new '
    pop.save_settings(None)
    assert app.config_manager.openai_api_key == 'sk-new'

    m.App._running_app = None
    pop2 = m.SettingsPopup()
    assert pop2.api_input.text == ''
    pop2.save_settings(None)


# ---------------------------------------------------------------- App core
def test_build_and_log(app):
    assert app.title == 'Luister'
    assert app.root.current == 'splash'
    app.log('x' * 200)
    assert app.main_screen.debug_label.text == 'x' * 100
    other = m.LuisterApp()
    other.log('no screen')


def test_scan_music_directories(app, tmp_path, monkeypatch):
    home = m.Path.home()
    (home / 'Music').mkdir()
    (home / 'Downloads').mkdir()
    old = make_audio(home / 'Music', 'old.mp3', 1000)
    new = make_audio(home / 'Downloads', 'new.FLAC', 2000)
    (home / 'Music' / 'note.txt').write_text('x')
    (home / 'Music' / 'dir.mp3').mkdir()
    app.scan_music_directories()
    assert app.playlist == [new, old]
    assert app.main_screen.title_label.text == '2 tracks found'

    def denied(p):
        raise PermissionError
    monkeypatch.setattr(m.os, 'listdir', denied)
    app.playlist = []
    app.scan_music_directories()
    assert app.playlist == []


def test_scan_android_dirs(app, monkeypatch):
    monkeypatch.setattr(m, 'platform', 'android')
    seen = []
    monkeypatch.setattr(m.os.path, 'exists', lambda p: seen.append(p) or False)
    app.scan_music_directories()
    assert '/storage/emulated/0/Music' in seen


def test_open_folder_and_selection(app, tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'HAS_FILECHOOSER', False)
    app.open_folder()
    assert app.main_screen.title_label.text == 'File picker not available'

    monkeypatch.setattr(m, 'HAS_FILECHOOSER', True)
    opened = {}
    fc = types.SimpleNamespace(open_file=lambda **kw: opened.update(kw))
    monkeypatch.setattr(m, 'filechooser', fc, raising=False)
    app.open_folder()
    assert opened['multiple'] is True

    def boom(**kw):
        raise RuntimeError('picker exploded and more text')
    monkeypatch.setattr(m, 'filechooser', types.SimpleNamespace(open_file=boom), raising=False)
    app.open_folder()
    assert app.main_screen.title_label.text.startswith('Error: picker')

    monkeypatch.setattr(m, 'load_audio', lambda p, logger=None, on_complete=None: FakeSound())
    app._on_files_selected([])
    app._on_files_selected(['/a/b.txt'])
    assert app.playlist == []
    a = make_audio(tmp_path, 'a.mp3')
    app._on_files_selected([a, '/a/b.txt'])
    assert app.playlist == [a] and app.is_playing
    assert app.config_manager.last_playlist == [a]


def test_playback_controls(app, tmp_path, monkeypatch):
    files = [make_audio(tmp_path, f't{i}.mp3') for i in range(3)]
    sounds = []

    def loader(p, logger=None, on_complete=None):
        s = FakeSound()
        sounds.append(s)
        return s
    monkeypatch.setattr(m, 'load_audio', loader)
    app.playlist = files

    app.toggle_play()  # no sound -> play index 0
    assert app.is_playing and app.current_index == 0
    app.toggle_play()
    assert not app.is_playing
    app.toggle_play()
    assert app.is_playing

    app.next_track()
    assert app.current_index == 1
    app.prev_track()
    assert app.current_index == 0
    app.prev_track()
    assert app.current_index == 2
    app.toggle_loop()
    assert app.is_looping
    app.next_track()
    assert app.current_index == 2
    app.toggle_loop()
    app.next_track()
    assert app.current_index == 0

    app.seek(0.5)
    assert ('seek', 50.0) in app.sound.calls
    orig_seek = app.sound.seek
    app.sound.seek = lambda p: (_ for _ in ()).throw(RuntimeError('x'))
    app.seek(0.5)
    app.sound.seek = orig_seek
    app.sound.length = 0
    app.seek(0.5)
    app.sound.length = 100
    app.set_volume(0.3)
    assert app.sound.volume == 0.3 and app.config_manager.volume == 0.3

    app.stop_playback()
    assert not app.is_playing

    app.current_index = -1
    app.sound = None
    app.toggle_play()
    assert app.current_index == 0
    app.sound = None
    app.stop_playback()
    app.seek(0.1)
    app.set_volume(0.5)

    app.play_index(99)  # out of range

    app.sound = FakeSound()
    app.clear_playlist()
    assert app.playlist == [] and app.current_index == -1
    app.clear_playlist()
    app.next_track()
    app.prev_track()
    app.toggle_play()


def test_shuffle(app, monkeypatch):
    app.shuffle_playlist()
    app.playlist = ['/a/1.mp3', '/a/2.mp3', '/a/3.mp3']
    app.current_index = 1
    monkeypatch.setattr(m.random, 'shuffle', lambda l: l.reverse())
    app.shuffle_playlist()
    assert app.playlist[app.current_index] == '/a/2.mp3'
    app.current_index = -1
    app.shuffle_playlist()
    assert app.current_index == -1
    # current track vanishes during shuffle
    app.current_index = 0
    monkeypatch.setattr(m.random, 'shuffle', lambda l: l.__setitem__(slice(None), ['x', 'y', 'z']))
    app.shuffle_playlist()
    assert app.current_index == 0


def test_load_track_paths(app, tmp_path, monkeypatch):
    a = make_audio(tmp_path, 'a.mp3')
    old = FakeSound()
    app.sound = old
    monkeypatch.setattr(m, 'load_audio', lambda p, logger=None, on_complete=None: None)
    assert app.load_track(a) is False
    assert 'unload' in old.calls and app.sound is None

    def boom(p, logger=None, on_complete=None):
        raise RuntimeError('bad')
    monkeypatch.setattr(m, 'load_audio', boom)
    assert app.load_track(a) is False

    monkeypatch.setattr(m, 'load_audio', lambda p, logger=None, on_complete=None: FakeSound(length=0))
    assert app.load_track(a) is True


def test_update_position(app, monkeypatch):
    app._update_position(0)  # no sound
    app.sound = FakeSound(length=100, pos=10)
    app._update_position(0)  # not playing
    app.is_playing = True
    app.playlist = ['/a.mp3', '/b.mp3']
    app.current_index = 0
    app._update_position(0)  # Kivy-style .pos
    assert app.main_screen.visualizer is not None

    # Android-style player
    s = FakeSound(length=100)
    s.is_playing = lambda: False
    s.get_pos = lambda: 5
    app.sound = s
    app._update_position(0)
    assert 'play' in s.calls

    s.is_playing = lambda: True
    s.get_pos = lambda: None
    s.length = 0
    app._update_position(0)

    # end of track -> next track
    monkeypatch.setattr(m, 'load_audio', lambda p, logger=None, on_complete=None: FakeSound())
    s2 = FakeSound(length=10, pos=9.8)
    app.sound = s2
    app._update_position(0)
    assert app.current_index == 1

    # error swallowed
    s3 = FakeSound()
    s3.pos = 'bad'
    app.sound = s3
    app._update_position(0)


# ---------------------------------------------------------------- lifecycle
def test_on_start_restores_playlist_and_stop(app, tmp_path):
    f1 = make_audio(tmp_path, 'a.mp3')
    app.config_manager.last_playlist = [f1, '/missing.mp3']
    app.config_manager.last_index = 5
    app.config_manager.volume = 0.4
    app.on_start()
    assert app.playlist == [f1] and app.current_index == 0
    assert app.main_screen.volume_slider.value == pytest.approx(40)

    app.sound = FakeSound()
    app.playlist = [f1]
    app.on_stop()
    assert app.config_manager.last_playlist == [f1]
    assert 'stop' in app.sound.calls

    app._update_event = None
    app.sound = None
    app.on_stop()


def test_on_start_scans_when_no_playlist(app, monkeypatch):
    scans = []
    monkeypatch.setattr(app, 'scan_music_directories', lambda: scans.append(1))
    app.config_manager.last_playlist = ['/missing.mp3']
    app.on_start()
    assert scans == [1]


def install_fake_android(monkeypatch, api, tmp_path):
    requested = {}
    perm = types.SimpleNamespace(READ_MEDIA_AUDIO='AUDIO', READ_EXTERNAL_STORAGE='EXT')
    android = types.ModuleType('android')
    android.api_version = api
    perms = types.ModuleType('android.permissions')
    perms.Permission = perm
    perms.request_permissions = lambda p, cb: requested.update(p=p, cb=cb)
    storage = types.ModuleType('android.storage')
    storage.app_storage_path = lambda: str(tmp_path / 'astore')
    android.permissions = perms
    android.storage = storage
    monkeypatch.setitem(sys.modules, 'android', android)
    monkeypatch.setitem(sys.modules, 'android.permissions', perms)
    monkeypatch.setitem(sys.modules, 'android.storage', storage)
    return requested


@pytest.mark.parametrize('api,expected', [(34, 'AUDIO'), (30, 'EXT')])
def test_android_permissions(app, monkeypatch, tmp_path, api, expected):
    monkeypatch.setattr(m, 'platform', 'android')
    req = install_fake_android(monkeypatch, api, tmp_path)
    scans = []
    monkeypatch.setattr(app, 'scan_music_directories', lambda: scans.append(1))
    app.on_start()
    assert req['p'] == [expected] + (['android.permission.POST_NOTIFICATIONS'] if api >= 33 else [])
    scans.clear()
    req['cb']([expected], [True])
    assert scans == [1]
    scans.clear()
    req['cb']([expected], [False])
    app.playlist = ['/x.mp3']
    req['cb']([expected], [True])
    assert scans == []


def test_main_runs_app(monkeypatch):
    ran = []
    monkeypatch.setattr(m.LuisterApp, 'run', lambda self: ran.append(self))
    m.main()
    assert len(ran) == 1


def test_module_entrypoint(monkeypatch):
    import runpy
    ran = []
    monkeypatch.setattr(m.App, 'run', lambda self: ran.append(self))
    runpy.run_path(m.__file__, run_name='__main__')
    assert len(ran) == 1


def test_back_key(app):
    class Win:
        children = []

    win = Win()
    assert app._on_key(win, 13) is False  # not the back key
    app.root.current = 'main'
    assert app._on_key(win, 27) is False  # nothing to close: system default
    app.root.current = 'playlist'
    assert app._on_key(win, 27) is True and app.root.current == 'main'
    app.root = None
    assert app._on_key(win, 27) is False

    closed = []
    popup = m.YouTubeDownloadPopup()
    popup.dismiss = lambda *a: closed.append(1)
    win.children = [popup]
    assert app._on_key(win, 27) is True and closed == [1]
