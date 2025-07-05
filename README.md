<center><img src='https://upload.wikimedia.org/wikipedia/commons/thumb/e/e6/Python_and_Qt.svg/1200px-Python_and_Qt.svg.png' width=64 height=64></center>

# Luister

A modern, Python-powered media player inspired by the classics.

---

## Contents

- [Info](#info)  
  Information about the libraries and tools used.
- [Luister Features](#luister-features)  
  Explore the functionality and user experience.
- [Get Started](#get-started)  
  How to clone, set up, and run Luister on your computer.

---

## <a name="info"></a>Info

**Luister** is built using the following technologies:

- **PyQt5**: A powerful set of Python bindings for the Qt application framework, allowing for the creation of modern, cross-platform GUIs.
- **pyqt5-tools**: Provides essential developer tools like Qt Designer, which are not bundled with the main PyQt5 package.

---

## <a name="luister-features"></a>Luister Features

Luister brings the spirit of classic media players into the Python era, with a sleek interface and all the features you expect:

- **Playlist Management:**  
  Easily add your favorite songs to the playlist. If the playlist is empty, playback controls are disabled to keep things tidy.

  <center><img alt="player1" src="https://user-images.githubusercontent.com/97242088/210106051-17e6ff27-8988-44a1-92ba-56689c57b4ef.png"></center>

- **Simple Song Selection:**  
  Click the 'arrow up' button to open a file dialog. Select your music files (hold Ctrl to select multiple), and hit 'Open'. The playlist window will appear automatically.

  <center><img alt='add_files' src='https://user-images.githubusercontent.com/97242088/210106049-7531e769-bb56-4ab8-8e4d-320f5f3893f1.png'></center>

- **Intuitive Controls:**  
  Once your playlist is loaded, all controls become active:

  | Button | Function |
  |--------|----------|
  | <img src="https://img.icons8.com/fluency-systems-filled/48/null/chevron-left--v2.png" height='20' width='20'/> | Previous song |
  | <img src="https://img.icons8.com/ios-glyphs/30/null/play--v1.png" height='20' width='20'/> | Play |
  | <img src="https://img.icons8.com/ios-glyphs/30/null/pause--v1.png" height='20' width='20'/> | Pause |
  | <img src="https://img.icons8.com/ios-filled/50/null/stop.png" height='20' width='20'/> | Stop (resets to start) |
  | <img src="https://img.icons8.com/external-others-inmotus-design/67/null/external-Right-basic-web-ui-elements-others-inmotus-design-2.png" height='20' width='20'/> | Next song |

- **Now Playing Display:**  
  The left LCD shows the current time; the right displays the song title and duration.

- **Time & Volume Sliders:**  
  Adjust playback position and volume on the fly.

- **Shuffle & Loop:**  
  - Shuffle: Randomizes your playlist order for a fresh experience.
  - Loop: Repeats the playlist when it ends.

  <center><img alt="song" src="https://user-images.githubusercontent.com/97242088/210106053-f152ab86-bd4a-4d5f-80f4-23ad4c7c07a3.png"></center>

- **Direct Song Selection:**  
  Click any song in the playlist to play it instantly.

- **Flexible Windows:**  
  The main player and playlist window can be used independently—close one and keep the other open!

  <center><img alt="song2" src="https://user-images.githubusercontent.com/97242088/210106054-1f8b6b43-2df8-43e6-a76c-c0f1354c9248.png"></center>

---

## <a name="get-started"></a>Get Started

Ready to try Luister? Just follow these steps:

### 1. Clone the Repository

Open your terminal and run:

```
git clone https://github.com/codesapienbe/luister
cd luister
```

### 2. Run the App

```
uv run luister
```

No extra commands needed! The app will launch, and you can start enjoying your music right away.

---

<center>
  <h2>Enjoy Luister!</h2>
  <p style="font-size:100px">&#129409;</p>
</center>

**Tip:** If you have any questions or want to contribute, check out the repository’s README or open an issue on GitHub.

>> **Happy listening!**

