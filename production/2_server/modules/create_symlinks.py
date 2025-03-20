#!/usr/bin/env python3
import os

def create_sequential_symlinks(source_dir, target_dir, prefix="multifile_", extension=".mp3", start_index=0):
    """
    Scans the source_dir for .mp3 files, sorts them, and creates symbolic links
    in target_dir with names like multifile_XXXX.mp3 so that they can be picked up by the GStreamer pipeline.
    """
    # Ensure the target directory exists.
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    
    # List all .mp3 files in the source directory.
    files = [f for f in os.listdir(source_dir) if f.lower().endswith(extension)]
    
    # Sort the files alphabetically. You could also sort by modification time if needed.
    files.sort()
    
    # Create symlinks with sequential names.
    for i, filename in enumerate(files, start=start_index):
        source_path = os.path.join(source_dir, filename)
        target_filename = f"{prefix}{i:04d}{extension}"
        target_path = os.path.join(target_dir, target_filename)
        
        # Remove existing symlink if it exists.
        if os.path.exists(target_path):
            os.remove(target_path)
        
        os.symlink(source_path, target_path)
        print(f"Created symlink: {target_path} -> {source_path}")

if __name__ == "__main__":
    source_directory = "/mnt/usb/Haut_Recs"
    target_directory = "/mnt/usb/Haut_Recs/ordered"
    create_sequential_symlinks(source_directory, target_directory, prefix="multifile_", extension=".mp3", start_index=0)
