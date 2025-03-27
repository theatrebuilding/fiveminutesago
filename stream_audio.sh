#!/bin/bash

# Define source and destination folders
SRC_DIR="/mnt/usb/Haut_Recs"
DEST_DIR="/mnt/usb/Haut_Recs2"

# Create destination directory
mkdir -p "$DEST_DIR"

# Copy all files to the new folder
cp -r "$SRC_DIR/"* "$DEST_DIR/"

# Go to the new directory
cd "$DEST_DIR" || exit

# Rename files sequentially for GStreamer's multifilesrc (audio_chunk_0001.mp3, audio_chunk_0002.mp3, ...)
i=1
for file in $(ls -1 | sort); do
    ext="${file##*.}"  # Get file extension (e.g., mp3)
    new_name=$(printf "audio_chunk_%04d.%s" "$i" "$ext")
    mv "$file" "$new_name"
    i=$((i+1))
done

echo "Folder copied and files renamed for GStreamer multifilesrc!"
