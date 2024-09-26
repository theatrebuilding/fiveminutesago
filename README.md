# Project Documentation

## Files and Descriptions

### `start_streaming.py`
- **Status**: Functional, but with a limitation.
- **Issue**: The broadcast is interrupted when a device is added or removed from the available streams.
  - **Potential Fix**: Ideally, this issue should be resolved within the Python code itself. However, a workaround could be implemented using JavaScript on the "Crying by the Sea" page to automatically restart the stream when a device change is detected.

### `audio_stream_recorder.py`
- **Status**: Should be functional, but needs verification.
- **Uncertainty**: The section that adds new files to the playlist may not be working as expected. Further testing is recommended.

### `config.json`
- **Purpose**: Contains stream and port settings.
- **Usage**: This file allows you to set the streams and port so they don’t need to be manually entered every time you run the program.

### `fiveminutesago.txt`
- **Description**: A simple ASCII art file.
- **Purpose**: Displays the title and version number in the terminal when the program is run.

## Notes
- If you encounter any issues or have feedback, please feel free to reach out.

