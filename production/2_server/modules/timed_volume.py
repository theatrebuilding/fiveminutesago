#!/usr/bin/env python3
import datetime
from gi.repository import Gst, GstController, GLib

def update_control_points(data):
    """
    This callback updates the control points for the interpolation control source (csource)
    so that the volume fades smoothly over 60 seconds.
    
    It determines the target volume based on the current time:
      - If the current minute is less than 15 or greater than or equal to 45, target_volume is 1.0.
      - Otherwise, target_volume is 0.0.
    
    It then reads the current volume from the volume element and, if it differs from the target,
    sets the control curve to fade from the current volume to the target over 60 seconds.
    """
    csource, volume_elem = data
    now = datetime.datetime.now()
    
    if now.minute < 15 or now.minute >= 45:
        target_volume = 1.0
    else:
        target_volume = 0.0

    current_volume = volume_elem.get_property("volume")
    if current_volume != target_volume:
        # Set control points: at time 0 use the current volume, and at 60 seconds use the target volume.
        csource.set_value_at_time(0 * Gst.SECOND, current_volume)
        csource.set_value_at_time(60 * Gst.SECOND, target_volume)
        print(f"Updated control points: fading from {current_volume} to {target_volume} over 60 seconds at {now.strftime('%H:%M:%S')}")
    else:
        print(f"No volume change needed at {now.strftime('%H:%M:%S')}")
    return True  # Continue calling every 60 seconds

def setup_dynamic_volume_control(volume_elem):
    """
    Attaches a GstController.InterpolationControlSource to the 'volume' property
    of the provided volume element so that changes in target volume occur as a smooth fade
    over 60 seconds. The control points are updated every 60 seconds.
    """
    # Create an interpolation control source.
    csource = GstController.InterpolationControlSource.new()
    csource.set_property("mode", GstController.InterpolationMode.LINEAR)
    
    # Attach the control source to the volume element's "volume" property.
    binding = GstController.DirectControlBinding.new(volume_elem, "volume", csource)
    volume_elem.add_control_binding(binding)
    
    # Set initial control points based on the current time.
    now = datetime.datetime.now()
    if now.minute < 15 or now.minute >= 45:
        initial_target = 1.0
    else:
        initial_target = 0.0

    # Get the current volume as the starting value.
    initial_value = volume_elem.get_property("volume")
    csource.set_value_at_time(0 * Gst.SECOND, initial_value)
    csource.set_value_at_time(60 * Gst.SECOND, initial_target)
    print(f"Initial dynamic volume: fading from {initial_value} to {initial_target} over 60 seconds at {now.strftime('%H:%M:%S')}")
    
    # Schedule periodic updates every 60 seconds.
    GLib.timeout_add_seconds(60, update_control_points, (csource, volume_elem))
