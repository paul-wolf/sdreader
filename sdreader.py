import os
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk
from datetime import datetime
import threading
import signal
import sys


def plog(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def is_sd_card_mac(device):
    result = subprocess.run(["diskutil", "info", device], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "Media Name" in line and "SD" in line:
            return True
    return False


def is_sd_card(device, mount_point):
    if os.name == "posix":
        if os.uname().sysname == "Darwin":
            return is_sd_card_mac(device)
        elif "mmcblk" in device or "sd" in device:
            return True
    elif os.name == "nt":
        result = subprocess.run(
            ["wmic", "logicaldisk", "where", f"DeviceID='{device}'", "get", "MediaType"],
            capture_output=True,
            text=True,
        )
        if "Removable Media" in result.stdout:
            return True
    return False


def read_mounts_mac():
    mounts = []
    result = subprocess.run(["mount"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        parts = line.split()
        device = parts[0]
        mount_point = parts[2]
        filesystem_type = parts[4].strip("()")
        options = parts[5].strip("()")
        mount_info = {
            "device": device,
            "mount_point": mount_point,
            "filesystem_type": filesystem_type,
            "options": options,
            "is_sd_card": is_sd_card(device, mount_point),
        }
        mounts.append(mount_info)
    return mounts


def read_mounts_linux():
    mounts = []
    with open("/proc/mounts", "r") as f:
        for line in f:
            parts = line.split()
            device = parts[0]
            mount_point = parts[1]
            mount_info = {
                "device": device,
                "mount_point": mount_point,
                "filesystem_type": parts[2],
                "options": parts[3],
                "dump": parts[4],
                "pass": parts[5],
                "is_sd_card": is_sd_card(device, mount_point),
            }
            mounts.append(mount_info)
    return mounts


def read_mounts_windows():
    mounts = []
    result = subprocess.run(
        ["wmic", "logicaldisk", "get", "DeviceID,FileSystem,Size,FreeSpace"],
        capture_output=True,
        text=True,
    )
    lines = result.stdout.splitlines()
    keys = [key.strip() for key in lines[0].split()]
    for line in lines[1:]:
        if line.strip():
            values = line.split()
            mount_info = dict(zip(keys, values))
            mount_info["is_sd_card"] = is_sd_card(mount_info["DeviceID"], None)
            mounts.append(mount_info)
    return mounts


def get_mounts():
    if os.name == "posix":
        if os.uname().sysname == "Darwin":
            return read_mounts_mac()
        else:
            return read_mounts_linux()
    elif os.name == "nt":
        return read_mounts_windows()
    return []


def write_selected_mounts(selected_mounts, filename="selected_mounts.txt"):
    with open(filename, "w") as f:
        for mount in selected_mounts:
            f.write(f"{mount}\n")


def copy_sd_card_contents(mount_point, destination_dir):
    if not os.path.exists(destination_dir):
        os.makedirs(destination_dir)
    for root, dirs, files in os.walk(mount_point):
        relative_path = os.path.relpath(root, mount_point)
        dest_path = os.path.join(destination_dir, relative_path)
        if not os.path.exists(dest_path):
            os.makedirs(dest_path)
        for file in files:
            src_file = os.path.join(root, file)
            dest_file = os.path.join(dest_path, file)
            try:
                shutil.copy2(src_file, dest_file)
                plog(f"Copied {src_file} to {dest_file}")
            except PermissionError:
                plog(f"Permission denied: {src_file}")
                continue


def format_sd_card(device):
    if os.name == "posix":
        if os.uname().sysname == "Darwin":
            # macOS: Use diskutil to erase the disk
            plog(f"Formatting {device} on macOS")
            subprocess.run(["diskutil", "eraseDisk", "JHFS+", "SDCard", device])
        else:
            # Linux: Use mkfs to format the disk
            plog(f"Formatting {device} on Linux")
            subprocess.run(["mkfs.ext4", device])
    elif os.name == "nt":
        # Windows: Use format command
        plog(f"Formatting {device} on Windows")
        subprocess.run(["format", device, "/FS:NTFS", "/P:1"], input=b"Y\n", text=True)


def create_gui(mounts):
    root = tk.Tk()
    root.title("Select Mount Points")

    selected_mounts = []

    def on_select():
        selected_mounts.clear()
        for var, mount in zip(checkbox_vars, mounts):
            if var.get():
                selected_mounts.append(mount["mount_point"])
        # write_selected_mounts(selected_mounts)
        root.quit()

    def on_format():
        selected_mounts.clear()
        for var, mount in zip(checkbox_vars, mounts):
            if var.get():
                selected_mounts.append(mount["device"])
        root.quit()
        for device in selected_mounts:
            format_sd_card(device)

    frame = ttk.Frame(root, padding="10")
    frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    checkbox_vars = []
    for mount in mounts:
        var = tk.BooleanVar()
        checkbox = ttk.Checkbutton(frame, text=f"{mount['mount_point']} ({mount['device']})", variable=var)
        checkbox.grid(sticky=tk.W)
        checkbox_vars.append(var)

    button_save = ttk.Button(frame, text="Save Selected Mounts", command=on_select)
    button_save.grid(sticky=tk.W)

    button_format = ttk.Button(frame, text="Format Mounts", command=on_format)
    button_format.grid(sticky=tk.W)

    # Center the window on the screen
    root.update_idletasks()
    window_width = root.winfo_width()
    window_height = root.winfo_height()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    position_top = int(screen_height / 2 - window_height / 2)
    position_right = int(screen_width / 2 - window_width / 2)
    root.geometry(f"{window_width}x{window_height}+{position_right}+{position_top}")

    root.mainloop()

    # After the GUI is closed, start the copy process
    if selected_mounts:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_destination_dir = f"./data-{timestamp}"
        os.makedirs(base_destination_dir, exist_ok=True)

        def copy_files():
            for i, mount_point in enumerate(selected_mounts):
                mount_name = os.path.basename(mount_point.strip("/"))
                unique_destination_dir = os.path.join(base_destination_dir, f"{mount_name}_{i}")
                copy_sd_card_contents(mount_point, unique_destination_dir)

        threading.Thread(target=copy_files).start()


def signal_handler(sig, frame):
    plog("Exiting gracefully...")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    mounts = get_mounts()
    mounts = [m for m in mounts if "/Volumes" in m["mount_point"] and "/System/Volumes" not in m["mount_point"]]
    create_gui(mounts)
