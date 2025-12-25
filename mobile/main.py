"""
Luister Mobile - Kivy-based Android music player
Entry point for Buildozer Android builds
"""

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.properties import StringProperty, NumericProperty, BooleanProperty
from kivy.graphics import Color, Rectangle, RoundedRectangle

import os
from pathlib import Path


class VisualizerWidget(BoxLayout):
    """Simple spectrum visualizer using Kivy graphics"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bars = 16
        self.magnitudes = [0.0] * self.bars
        self.bind(size=self._draw_bars, pos=self._draw_bars)
        Clock.schedule_interval(self._animate_demo, 1/30)  # 30 FPS demo animation

    def _animate_demo(self, dt):
        """Demo animation - replace with real audio analysis"""
        import random
        for i in range(self.bars):
            # Smooth random movement
            target = random.random() * 0.8
            self.magnitudes[i] += (target - self.magnitudes[i]) * 0.3
        self._draw_bars()

    def _draw_bars(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            bar_width = self.width / self.bars
            for i, mag in enumerate(self.magnitudes):
                # Gradient: blue to cyan based on magnitude
                Color(0.2, 0.6 + mag * 0.4, 1.0, 0.9)
                bar_height = max(dp(4), mag * self.height * 0.9)
                Rectangle(
                    pos=(self.x + i * bar_width + dp(2), self.y),
                    size=(bar_width - dp(4), bar_height)
                )


class PlayerControls(BoxLayout):
    """Touch-friendly player control buttons"""

    is_playing = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
        self.spacing = dp(16)
        self.padding = [dp(16), dp(8)]

        # Previous button
        self.prev_btn = Button(
            text='<<',
            size_hint=(None, 1),
            width=dp(64),
            font_size=dp(24)
        )
        self.prev_btn.bind(on_press=self.on_prev)
        self.add_widget(self.prev_btn)

        # Play/Pause button (larger)
        self.play_btn = Button(
            text='Play',
            size_hint=(None, 1),
            width=dp(100),
            font_size=dp(20)
        )
        self.play_btn.bind(on_press=self.on_play)
        self.add_widget(self.play_btn)

        # Next button
        self.next_btn = Button(
            text='>>',
            size_hint=(None, 1),
            width=dp(64),
            font_size=dp(24)
        )
        self.next_btn.bind(on_press=self.on_next)
        self.add_widget(self.next_btn)

    def on_prev(self, instance):
        app = App.get_running_app()
        if app:
            app.prev_track()

    def on_play(self, instance):
        app = App.get_running_app()
        if app:
            app.toggle_play()

    def on_next(self, instance):
        app = App.get_running_app()
        if app:
            app.next_track()

    def update_play_button(self, is_playing):
        self.is_playing = is_playing
        self.play_btn.text = 'Pause' if is_playing else 'Play'


class MainScreen(Screen):
    """Main player screen with visualizer and controls"""

    track_title = StringProperty('No track loaded')
    current_time = StringProperty('0:00')
    total_time = StringProperty('0:00')
    progress = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = BoxLayout(orientation='vertical', padding=dp(16), spacing=dp(8))

        # Track title
        self.title_label = Label(
            text=self.track_title,
            size_hint=(1, 0.1),
            font_size=dp(18),
            halign='center',
            valign='middle'
        )
        self.title_label.bind(size=self.title_label.setter('text_size'))
        layout.add_widget(self.title_label)

        # Visualizer
        self.visualizer = VisualizerWidget(size_hint=(1, 0.4))
        layout.add_widget(self.visualizer)

        # Time display
        time_layout = BoxLayout(size_hint=(1, 0.05), spacing=dp(8))
        self.time_current = Label(text='0:00', size_hint=(0.2, 1), font_size=dp(14))
        self.time_total = Label(text='0:00', size_hint=(0.2, 1), font_size=dp(14))
        time_layout.add_widget(self.time_current)
        time_layout.add_widget(Label(size_hint=(0.6, 1)))  # Spacer
        time_layout.add_widget(self.time_total)
        layout.add_widget(time_layout)

        # Progress slider
        self.progress_slider = Slider(
            min=0,
            max=100,
            value=0,
            size_hint=(1, 0.08)
        )
        self.progress_slider.bind(on_touch_up=self.on_seek)
        layout.add_widget(self.progress_slider)

        # Volume slider
        volume_layout = BoxLayout(size_hint=(1, 0.08), spacing=dp(8))
        volume_layout.add_widget(Label(text='Vol', size_hint=(0.15, 1), font_size=dp(14)))
        self.volume_slider = Slider(
            min=0,
            max=100,
            value=70,
            size_hint=(0.85, 1)
        )
        self.volume_slider.bind(value=self.on_volume)
        volume_layout.add_widget(self.volume_slider)
        layout.add_widget(volume_layout)

        # Player controls
        self.controls = PlayerControls(size_hint=(1, 0.15))
        layout.add_widget(self.controls)

        # Bottom buttons (Playlist, Settings)
        bottom_layout = BoxLayout(size_hint=(1, 0.1), spacing=dp(16))

        self.playlist_btn = Button(text='Playlist', font_size=dp(16))
        self.playlist_btn.bind(on_press=self.open_playlist)
        bottom_layout.add_widget(self.playlist_btn)

        self.open_btn = Button(text='Open', font_size=dp(16))
        self.open_btn.bind(on_press=self.open_file)
        bottom_layout.add_widget(self.open_btn)

        layout.add_widget(bottom_layout)

        self.add_widget(layout)

    def on_seek(self, instance, touch):
        if instance.collide_point(*touch.pos):
            app = App.get_running_app()
            if app and app.sound:
                app.seek(instance.value / 100)

    def on_volume(self, instance, value):
        app = App.get_running_app()
        if app:
            app.set_volume(value / 100)

    def open_playlist(self, instance):
        app = App.get_running_app()
        if app:
            app.root.current = 'playlist'

    def open_file(self, instance):
        # TODO: Implement file picker using plyer or android.storage
        pass

    def update_track_info(self, title, duration):
        self.title_label.text = title
        mins, secs = divmod(int(duration), 60)
        self.time_total.text = f'{mins}:{secs:02d}'

    def update_position(self, position, duration):
        if duration > 0:
            self.progress_slider.value = (position / duration) * 100
            mins, secs = divmod(int(position), 60)
            self.time_current.text = f'{mins}:{secs:02d}'


class PlaylistScreen(Screen):
    """Playlist management screen"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = BoxLayout(orientation='vertical', padding=dp(16), spacing=dp(8))

        # Header
        header = BoxLayout(size_hint=(1, 0.1), spacing=dp(8))
        back_btn = Button(text='< Back', size_hint=(0.3, 1))
        back_btn.bind(on_press=self.go_back)
        header.add_widget(back_btn)
        header.add_widget(Label(text='Playlist', size_hint=(0.7, 1), font_size=dp(20)))
        layout.add_widget(header)

        # Playlist items (placeholder)
        from kivy.uix.scrollview import ScrollView
        from kivy.uix.gridlayout import GridLayout

        scroll = ScrollView(size_hint=(1, 0.85))
        self.playlist_grid = GridLayout(cols=1, spacing=dp(4), size_hint_y=None)
        self.playlist_grid.bind(minimum_height=self.playlist_grid.setter('height'))

        # Add placeholder items
        for i in range(1, 6):
            item = Button(
                text=f'Track {i} - Sample Song',
                size_hint_y=None,
                height=dp(48),
                font_size=dp(14)
            )
            item.bind(on_press=lambda x, idx=i-1: self.play_track(idx))
            self.playlist_grid.add_widget(item)

        scroll.add_widget(self.playlist_grid)
        layout.add_widget(scroll)

        # Bottom actions
        actions = BoxLayout(size_hint=(1, 0.08), spacing=dp(8))
        add_btn = Button(text='Add Files')
        add_btn.bind(on_press=self.add_files)
        actions.add_widget(add_btn)

        clear_btn = Button(text='Clear All')
        clear_btn.bind(on_press=self.clear_playlist)
        actions.add_widget(clear_btn)

        layout.add_widget(actions)

        self.add_widget(layout)

    def go_back(self, instance):
        app = App.get_running_app()
        if app:
            app.root.current = 'main'

    def play_track(self, index):
        app = App.get_running_app()
        if app:
            app.play_index(index)
            app.root.current = 'main'

    def add_files(self, instance):
        # TODO: Implement file picker
        pass

    def clear_playlist(self, instance):
        app = App.get_running_app()
        if app:
            app.clear_playlist()
        self.playlist_grid.clear_widgets()


class LuisterApp(App):
    """Main Kivy application"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sound = None
        self.playlist = []
        self.current_index = -1
        self.is_playing = False
        self._update_event = None

    def build(self):
        self.title = 'Luister'

        sm = ScreenManager()
        self.main_screen = MainScreen(name='main')
        self.playlist_screen = PlaylistScreen(name='playlist')

        sm.add_widget(self.main_screen)
        sm.add_widget(self.playlist_screen)

        return sm

    def on_start(self):
        # Start position update loop
        self._update_event = Clock.schedule_interval(self._update_position, 0.1)

        # Load sample/demo content on Android
        self._load_demo_content()

    def on_stop(self):
        if self._update_event:
            self._update_event.cancel()
        if self.sound:
            self.sound.stop()

    def _load_demo_content(self):
        """Load demo content or scan music folder"""
        # On Android, check common music locations
        music_dirs = [
            '/storage/emulated/0/Music',
            '/storage/emulated/0/Download',
            str(Path.home() / 'Music'),
        ]

        audio_exts = {'.mp3', '.wav', '.ogg', '.m4a', '.flac'}

        for music_dir in music_dirs:
            if os.path.exists(music_dir):
                try:
                    for f in os.listdir(music_dir)[:20]:  # Limit to 20 files
                        if Path(f).suffix.lower() in audio_exts:
                            self.playlist.append(os.path.join(music_dir, f))
                except PermissionError:
                    pass

        if self.playlist:
            self.main_screen.update_track_info(
                f'{len(self.playlist)} tracks loaded',
                0
            )

    def _update_position(self, dt):
        if self.sound and self.is_playing:
            pos = self.sound.get_pos() or 0
            length = self.sound.length or 1
            self.main_screen.update_position(pos, length)

    def load_track(self, path):
        """Load an audio file"""
        if self.sound:
            self.sound.stop()
            self.sound.unload()

        self.sound = SoundLoader.load(path)
        if self.sound:
            title = Path(path).stem
            self.main_screen.update_track_info(title, self.sound.length or 0)
            return True
        return False

    def toggle_play(self):
        """Toggle play/pause"""
        if not self.sound and self.playlist:
            self.play_index(0)
            return

        if self.sound:
            if self.is_playing:
                self.sound.stop()
                self.is_playing = False
            else:
                self.sound.play()
                self.is_playing = True

            self.main_screen.controls.update_play_button(self.is_playing)

    def play_index(self, index):
        """Play track at playlist index"""
        if 0 <= index < len(self.playlist):
            self.current_index = index
            if self.load_track(self.playlist[index]):
                self.sound.play()
                self.is_playing = True
                self.main_screen.controls.update_play_button(True)

    def next_track(self):
        """Play next track"""
        if self.playlist:
            next_idx = (self.current_index + 1) % len(self.playlist)
            self.play_index(next_idx)

    def prev_track(self):
        """Play previous track"""
        if self.playlist:
            prev_idx = (self.current_index - 1) % len(self.playlist)
            self.play_index(prev_idx)

    def seek(self, percent):
        """Seek to position (0.0 - 1.0)"""
        if self.sound:
            self.sound.seek(percent * self.sound.length)

    def set_volume(self, level):
        """Set volume (0.0 - 1.0)"""
        if self.sound:
            self.sound.volume = level

    def clear_playlist(self):
        """Clear the playlist"""
        if self.sound:
            self.sound.stop()
            self.sound.unload()
            self.sound = None
        self.playlist = []
        self.current_index = -1
        self.is_playing = False
        self.main_screen.controls.update_play_button(False)


def main():
    LuisterApp().run()


if __name__ == '__main__':
    main()
