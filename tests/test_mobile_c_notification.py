"""Tests for the Android media notification, wake lock and background transport."""

import sys
import types
from unittest.mock import MagicMock

import pytest

from tests.helpers_mobile import load_mobile_main
from tests.test_mobile_b_app import FakeSound, app  # noqa: F401  (app is a fixture)

m = load_mobile_main()


@pytest.fixture
def fake_android(monkeypatch):
    """Fake jnius + android.broadcast; returns the recorded Java-side mocks."""
    classes = {}

    def autoclass(name):
        if name not in classes:
            c = MagicMock(name=name)
            if name == 'android.os.Build$VERSION':
                c.SDK_INT = 34
            if name == 'org.kivy.android.PythonActivity':
                c.mActivity.getPackageName.return_value = 'be.test'
            classes[name] = c
        return classes[name]

    jnius = types.ModuleType('jnius')
    jnius.autoclass = autoclass
    jnius.PythonJavaClass = object
    jnius.java_method = lambda sig: (lambda f: f)
    broadcast = types.ModuleType('android.broadcast')

    class FakeReceiver:
        def __init__(self, callback, actions=None):
            self.callback = callback
            self.actions = actions
            self.receiver = object()
            self.receiver_filter = object()

    broadcast.BroadcastReceiver = FakeReceiver
    monkeypatch.setitem(sys.modules, 'jnius', jnius)
    monkeypatch.setitem(sys.modules, 'android', types.ModuleType('android'))
    monkeypatch.setitem(sys.modules, 'android.broadcast', broadcast)
    return classes


def test_completion_listener(fake_android):
    calls = []
    listener = m._make_completion_listener(lambda: calls.append(1))
    listener.onCompletion(None)
    assert calls == [1]


def test_player_wake_lock_and_listener(fake_android):
    calls = []
    p = m.AndroidMediaPlayer('/a.mp3', on_complete=lambda: calls.append(1))
    player = fake_android['android.media.MediaPlayer'].return_value
    player.setWakeMode.assert_called_once()
    player.setOnCompletionListener.assert_called_once_with(p._listener)
    m.AndroidMediaPlayer('/a.mp3')  # no listener


@pytest.mark.parametrize('sdk', [34, 28, 25])
def test_notification_lifecycle(fake_android, sdk):
    autoclass = sys.modules['jnius'].autoclass
    autoclass('android.os.Build$VERSION').SDK_INT = sdk
    actions = []
    n = m.AndroidMediaNotification(actions.append)
    ctx = autoclass('org.kivy.android.PythonActivity').mActivity
    ctx.registerReceiver.assert_called_once()
    assert (len(ctx.registerReceiver.call_args.args) == 5) == (sdk >= 33)
    assert bool(autoclass('android.app.NotificationChannel').called) == (sdk >= 26)

    n._on_broadcast(None, MagicMock(**{'getAction.return_value': n.ACTIONS['next']}))
    n._on_broadcast(None, MagicMock(**{'getAction.return_value': 'other'}))
    assert actions == ['next']

    n.show('Song', True)
    n.show('Song', False)
    assert n._nm.notify.call_count == 2

    n.cancel()
    n._nm.cancel.assert_called_once_with(n.NOTIFICATION_ID)
    ctx.unregisterReceiver.side_effect = RuntimeError
    n.cancel()  # unregister failure is ignored


def test_publish_state(app):  # noqa: F811
    app._publish_state()  # no notification
    notif = MagicMock()
    app._notification = notif
    app._publish_state()
    notif.show.assert_called_with('Luister', False)
    app.playlist = ['/x/song.mp3']
    app.current_index = 0
    app.is_playing = True
    app._publish_state()
    notif.show.assert_called_with('song', True)
    notif.show.side_effect = RuntimeError('boom')
    app._publish_state()


def test_setup_media_notification(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(m, 'AndroidMediaNotification', lambda cb: 'notif')
    app._setup_media_notification()
    assert app._notification == 'notif'

    def fail(cb):
        raise RuntimeError('nope')

    monkeypatch.setattr(m, 'AndroidMediaNotification', fail)
    app._setup_media_notification()
    assert app._notification is None


def test_notification_actions(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(m, 'load_audio',
                        lambda p, logger=None, on_complete=None: FakeSound())
    app.playlist = ['/a.mp3', '/b.mp3', '/c.mp3']
    app.current_index = 0

    app._on_notification_action('toggle')  # no sound -> starts current track
    assert app.is_playing and app.sound
    app._on_notification_action('toggle')  # pause
    assert not app.is_playing and 'stop' in app.sound.calls
    app._on_notification_action('toggle')  # resume
    assert app.is_playing
    app._on_notification_action('next')
    assert app.current_index == 1
    app._on_notification_action('prev')
    app._on_notification_action('prev')
    assert app.current_index == 2  # wraps around

    app.playlist = []
    app._on_notification_action('next')
    app._on_notification_action('prev')
    app.sound = None
    app._on_notification_action('toggle')  # nothing to play


def test_service_play_index_edges(app, monkeypatch):  # noqa: F811
    app.playlist = ['/a.mp3']
    app._service_play_index(5)
    monkeypatch.setattr(m, 'load_audio', lambda p, logger=None, on_complete=None: None)
    app._service_play_index(0)
    assert app.sound is None


def test_action_errors_are_swallowed(app, monkeypatch):  # noqa: F811
    def boom():
        raise RuntimeError('x')

    monkeypatch.setattr(app, '_service_toggle', boom)
    app._on_notification_action('toggle')


def test_track_complete(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(m, 'load_audio',
                        lambda p, logger=None, on_complete=None: FakeSound())
    app._on_track_complete()  # empty playlist
    app.playlist = ['/a.mp3', '/b.mp3']
    app.current_index = 1
    app._on_track_complete()
    assert app.current_index == 0
    app.is_looping = True
    app._on_track_complete()
    assert app.current_index == 0


def test_sync_ui_and_lifecycle(app, monkeypatch):  # noqa: F811
    app._sync_ui_from_state()  # no sound
    app.playlist = ['/a.mp3']
    app.current_index = 0
    app.sound = FakeSound(length=10)
    monkeypatch.setattr(app, 'load_lyrics_for_current_track', lambda: None)
    monkeypatch.setattr(app.main_screen.visualizer, 'set_audio', lambda p: None)
    app._sync_ui_from_state()
    assert app._ui_track_path == '/a.mp3'
    app.on_resume()
    assert app.on_pause() is True


def test_on_stop_cancels_notification(app):  # noqa: F811
    notif = MagicMock()
    app._notification = notif
    app.on_stop()
    notif.cancel.assert_called_once()
    assert app._notification is None


def test_update_position_android_end_of_track(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(m, 'platform', 'android')
    s = FakeSound(length=10)
    s.is_playing = lambda: False
    s.get_pos = lambda: 9.9
    app.sound = s
    app.is_playing = True
    app.playlist = ['/a.mp3', '/b.mp3']
    app.current_index = 0
    app._update_position(0)  # finished: left to the completion listener
    assert 'play' not in s.calls
    s.get_pos = lambda: 2
    app._update_position(0)  # mid-track stop: restarted
    assert 'play' in s.calls
