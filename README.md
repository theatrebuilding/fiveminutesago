## Files and Descriptions

### `start_streaming.py`
- **Status**: Functional, but with a limitation.
- **Issue**: The broadcast is interrupted for a couple seconds when a device is added or removed from the available streams.
  - **Potential Fix**: Ideally, this issue should be resolved within the Python code itself (maybe using pipes?). However, a workaround could be using JavaScript on the "Crying by the Sea" page to automatically restart the stream if the stream is dropped.

### `audio_stream_recorder.py`
- **Status**: Should be working, but needs verification.
- **Uncertainty**: The section that adds new files to the playlist may not be working as expected. Needs to be tested further.

### `config.json`
- **Purpose**: Contains stream and port settings.
- **Usage**: This file allows you to set the streams and port so they don’t need to be manually entered every time you run start_streaming.py.
- **TO-DO**: Add more things to the config file that can be set there rather than having to find and change in the python code.

### `fiveminutesago.txt`
- **Description**: A simple ASCII art file.
- **Purpose**: Displays the title and version number in the terminal when the program is run.

