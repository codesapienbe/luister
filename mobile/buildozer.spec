[app]
title = Luister
package.name = luister
package.domain = be.codesapien
version = 0.1.0

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
source.exclude_dirs = .buildozer,bin,__pycache__
icon.filename = %(source.dir)s/assets/icon.png

# p4a always shows a presplash before Python starts. A transparent image on the app
# background colour hides the Kivy logo so only the in-app SplashScreen is visible.
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #1C1C1E

# Pure-python deps (yt-dlp, requests) need no recipe; numpy/kivy are cross-compiled.
requirements = python3,kivy==2.3.1,pyjnius,android,plyer,numpy,requests,urllib3,idna,charset-normalizer,certifi,yt-dlp

orientation = portrait
fullscreen = 0

# READ_MEDIA_AUDIO covers Android 13+, READ_EXTERNAL_STORAGE covers older versions;
# POST_NOTIFICATIONS is needed for the playback notification on Android 13+.
android.permissions = INTERNET,READ_MEDIA_AUDIO,READ_EXTERNAL_STORAGE,POST_NOTIFICATIONS,WAKE_LOCK,RECORD_AUDIO
android.api = 35
android.minapi = 26
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
